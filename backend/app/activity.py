"""Is a person actually using the device?

A locked phone or tablet keeps talking to the internet: iCloud sync, app refresh, push keep-alives,
CDN fetches. That traffic is small and *repetitive*: the same few background hosts over and over.
When someone is actually using the device, it reaches lots of different user-facing hosts
(video segments, feeds, images, pages).

So we look at each device in short windows (default 5 minutes) and count the distinct
*foreground* hosts it contacted, ignoring:
  * lookups AdGuard blocked (trackers, ads)
  * apps marked as background / not screen time / System category
  * cloud & CDN infrastructure (cloudfront.net, akamai, googleapis, …)
A window with at least N foreground hosts (default 3) counts as "in use". Short gaps between
in-use windows are bridged so reading an article or watching a video isn't chopped up.

Measured on this network: locked iPad = 0-2 foreground hosts per 5 min, phone in use = 8-28.
"""
import threading
import time

from . import db, detect, psl
from . import settings_store as S

_cache: dict = {}
_lock = threading.Lock()
_site_cache: dict[str, bool] = {}


# Devices nobody "uses" like a screen: their traffic is never screen time.
NON_HUMAN_TYPES = {"router", "iot", "printer", "camera", "speaker"}


def non_human_device_ids() -> set[int]:
    marks = ",".join("?" * len(NON_HUMAN_TYPES))
    return {r["id"] for r in db.q(f"SELECT id FROM devices WHERE is_gateway=1 OR type IN ({marks})", tuple(NON_HUMAN_TYPES))}


def _background_service_ids() -> set[int]:
    return {r["id"] for r in db.q("SELECT id FROM services WHERE track_time=0 OR hidden=1 OR category='System'")}


# One app's own content network: only loads while someone scrolls or watches that app, so for "in use" it is
# real activity (detect still treats them as infrastructure so they never become apps of their own).
# Not whatsapp.net: WhatsApp downloads media in the background as messages arrive.
APP_CONTENT_CDNS = {"fbcdn.net", "cdninstagram.com", "ggpht.com", "nflxso.net"}


def _is_infra(domain: str) -> bool:
    v = _site_cache.get(domain)
    if v is None:
        site = psl.registrable(domain) or domain
        v = site not in APP_CONTENT_CDNS and detect.is_infrastructure(site)
        if len(_site_cache) > 50000:
            _site_cache.clear()
        _site_cache[domain] = v
    return v


# Background-chatter learning: an address a device contacts in a large share of *all* its awake time,
# used or not, says nothing about whether someone is using it (e.g. a phone pinging www.google.com every minute).
LEARN_DAYS = 7
LEARN_SLOT = 600             # judge presence in 10-minute slots
LEARN_MIN_AWAKE_SLOTS = 36   # need ~6 hours of the device's traffic before judging
LEARN_MIN_HOST_SLOTS = 12    # and the address in at least 2 hours' worth of slots
LEARN_SHARE = 0.40           # present in at least 40% of the device's awake slots → background
# With under a day of history the data may be one long session (e.g. an evening on Facebook), so only learn
# near-constant chatter until the device's history covers idle time (nights) too.
LEARN_FULL_SPAN = 86400
LEARN_SHARE_SHORT = 0.90
_learned: dict[int, set[str]] | None = None


def learned_background() -> dict[int, set[str]]:
    """device_id → addresses learned as that device's background chatter (empty if learning is off)."""
    global _learned
    if not S.get("activity_learn_background"):
        return {}
    with _lock:
        if _learned is None:
            m: dict[int, set[str]] = {}
            for r in db.q("SELECT device_id, domain FROM device_background"):
                m.setdefault(r["device_id"], set()).add(r["domain"])
            _learned = m
        return _learned


def learn_background(now: float | None = None) -> int:
    """Re-learn every device's background chatter from the last LEARN_DAYS days. Returns addresses learned."""
    global _learned
    now = now or time.time()
    lo = now - LEARN_DAYS * 86400
    skip = non_human_device_ids()
    bg = _background_service_ids()
    awake, span = {}, {}
    for r in db.q("SELECT device_id, COUNT(DISTINCT CAST(ts / ? AS INTEGER)) AS n, MIN(ts) AS first FROM dns_queries "
                  "WHERE ts>=? AND device_id IS NOT NULL GROUP BY device_id", (LEARN_SLOT, lo)):
        awake[r["device_id"]], span[r["device_id"]] = r["n"], now - r["first"]
    rows = []
    for r in db.q("SELECT device_id, domain, MAX(service_id) AS service_id, COUNT(DISTINCT CAST(ts / ? AS INTEGER)) AS n "
                  "FROM dns_queries WHERE ts>=? AND device_id IS NOT NULL AND blocked=0 AND domain IS NOT NULL "
                  "GROUP BY device_id, domain HAVING n>=?", (LEARN_SLOT, lo, LEARN_MIN_HOST_SLOTS)):
        did, total = r["device_id"], awake.get(r["device_id"], 0)
        if did in skip or total < LEARN_MIN_AWAKE_SLOTS or r["service_id"] in bg or _is_infra(r["domain"]):
            continue
        if (psl.registrable(r["domain"]) or r["domain"]) in APP_CONTENT_CDNS:
            continue  # content loading means someone is scrolling/watching, never chatter
        share = r["n"] / total
        if share >= (LEARN_SHARE if span[did] >= LEARN_FULL_SPAN else LEARN_SHARE_SHORT):
            rows.append((did, r["domain"], round(share, 3), now))
    with db.transaction() as c:
        c.execute("DELETE FROM device_background")
        c.executemany("INSERT INTO device_background(device_id, domain, share, learned) VALUES(?,?,?,?)", rows)
    with _lock:
        _learned = None
        _cache.clear()
    return len(rows)


def _app_specific(domain: str, service_id: int | None) -> bool:
    """True if the app matched via its own sub-address, not by claiming the whole shared site."""
    if not service_id:
        return False
    from .usage import match_service  # usage imports this module
    site = psl.registrable(domain) or domain
    return match_service(site) != service_id


def _params() -> tuple[int, int, int]:
    return (S.get("activity_window_min") * 60, S.get("activity_min_hosts"), S.get("activity_bridge_min") * 60)


def _foreground_hosts(lo: float, hi: float, device_id: int | None, bucket: int) -> dict[tuple[int, int], set]:
    bg = _background_service_ids()
    sql = "SELECT device_id, ts, domain, blocked, service_id FROM dns_queries WHERE ts>=? AND ts<? AND device_id IS NOT NULL"
    params: list = [lo, hi]
    if device_id:
        sql += " AND device_id=?"
        params.append(device_id)
    out: dict[tuple[int, int], set] = {}
    skip = non_human_device_ids()
    learned = learned_background()
    for r in db.q(sql, params):
        if r["device_id"] in skip or r["blocked"] or (r["service_id"] in bg) or not r["domain"] or _is_infra(r["domain"]):
            continue
        if r["domain"] in learned.get(r["device_id"], ()):
            continue
        out.setdefault((r["device_id"], int(r["ts"] // bucket)), set()).add(r["domain"])
    return out


def active_intervals(lo: float, hi: float, device_id: int | None = None) -> dict[int, list[tuple[float, float]]]:
    """device_id → merged [(start, end)] periods when a person was using the device, clipped to [lo, hi]."""
    if not S.get("activity_detection"):
        return {}
    bucket, min_hosts, bridge = _params()
    key = (int(lo // 60), int(hi // 60), device_id, bucket, min_hosts, bridge)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
    hosts = _foreground_hosts(lo - bucket, hi, device_id, bucket)
    per_dev: dict[int, list[int]] = {}
    for (did, b), hs in hosts.items():
        if len(hs) >= min_hosts:
            per_dev.setdefault(did, []).append(b)
    result: dict[int, list[tuple[float, float]]] = {}
    for did, bs in per_dev.items():
        spans: list[list[float]] = []
        for b in sorted(bs):
            s, e = b * bucket, (b + 1) * bucket
            if spans and s - spans[-1][1] <= bridge:
                spans[-1][1] = e
            else:
                spans.append([s, e])
        clipped = [(max(s, lo), min(e, hi)) for s, e in spans if e > lo and s < hi]
        if clipped:
            result[did] = clipped
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.time(), result)
    return result


def overlap(start: float, end: float, intervals: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(end, e) - max(start, s)) for s, e in intervals)


def total(intervals: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in intervals)


def current_activity(now: float | None = None) -> dict[int, dict]:
    """For each device someone is using right now: which apps (most recently opened first), since when.

    "Current app" = of the apps seen in the last activity window, the one whose session started most recently
    (ties: most lookups). "Since" = when its
    current session started, but never earlier than when the device's current in-use period began."""
    if not S.get("activity_detection"):
        return {}
    now = now or time.time()
    bucket, min_hosts, bridge = _params()
    gap = S.get("usage_session_gap_min") * 60
    bg = _background_service_ids()
    skip = non_human_device_ids()
    learned = learned_background()
    per: dict[int, dict] = {}
    for r in db.q("SELECT device_id, domain, service_id FROM dns_queries WHERE ts>=? AND ts<=? AND device_id IS NOT NULL "
                  "AND blocked=0", (now - bucket, now)):
        did = r["device_id"]
        if did in skip or r["service_id"] in bg or not r["domain"] or r["domain"] in learned.get(did, ()):
            continue
        infra = _is_infra(r["domain"])
        # Shared infrastructure (googleapis.com, …) is skipped, unless an app names that exact address
        # (e.g. photosdata-pa.googleapis.com → Google Photos): then it tells us the app, but isn't a "host".
        if infra and not _app_specific(r["domain"], r["service_id"]):
            continue
        e = per.setdefault(did, {"hosts": set(), "apps": {}, "domains": {}})
        if not infra:
            e["hosts"].add(r["domain"])
        if r["service_id"]:
            e["apps"][r["service_id"]] = e["apps"].get(r["service_id"], 0) + 1
            doms = e["domains"].setdefault(r["service_id"], {})
            doms[r["domain"]] = doms.get(r["domain"], 0) + 1
    if not per:
        return {}
    ivs_all = active_intervals(now - 12 * 3600, now)
    names = {s["id"]: s for s in db.q("SELECT id, name, category FROM services")}
    result: dict[int, dict] = {}
    for did, e in per.items():
        if len(e["hosts"]) < min_hosts:
            continue
        ivs = ivs_all.get(did, [])
        in_use_since = ivs[-1][0] if ivs and ivs[-1][1] >= now - bucket - bridge else now - bucket
        apps = []
        for sid, n in e["apps"].items():
            svc = names.get(sid)
            if not svc:
                continue
            sess = db.q1("SELECT start FROM usage_sessions WHERE device_id=? AND service_id=? AND end>=? AND start<=? "
                         "ORDER BY end DESC LIMIT 1", (did, sid, now - gap, now))
            since = max(sess["start"] if sess else now - bucket, in_use_since)
            top = max(e["domains"].get(sid, {"": 0}).items(), key=lambda x: x[1])[0]
            domain = (psl.registrable(top) or top) if top else None
            apps.append({"service_id": sid, "service": svc["name"], "category": svc["category"], "since": since, "lookups": n,
                         "domain": domain})
        # The app opened most recently is the one on screen; steady background pings started long ago.
        apps = sorted(apps, key=lambda a: (-a["since"], -a["lookups"]))[:4]
        result[did] = {"in_use_since": in_use_since, "apps": apps, "now": now}
    return result


def in_use_now(now: float | None = None) -> dict[int, bool]:
    """device_id → True if it reached enough foreground hosts in the last window."""
    if not S.get("activity_detection"):
        return {}
    now = now or time.time()
    bucket, min_hosts, _ = _params()
    hosts: dict[int, set] = {}
    bg = _background_service_ids()
    skip = non_human_device_ids()
    learned = learned_background()
    for r in db.q("SELECT device_id, domain, blocked, service_id FROM dns_queries WHERE ts>=? AND device_id IS NOT NULL",
                  (now - bucket,)):
        if r["device_id"] in skip or r["blocked"] or r["service_id"] in bg or not r["domain"] or _is_infra(r["domain"]):
            continue
        if r["domain"] in learned.get(r["device_id"], ()):
            continue
        hosts.setdefault(r["device_id"], set()).add(r["domain"])
    return {did: len(h) >= min_hosts for did, h in hosts.items()}
