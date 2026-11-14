"""Turns the AdGuard DNS log into per-device app usage.

Screen time is an estimate. When a device keeps looking up an app's domains, it's treated as
using that app. Lookups closer together than the 'session gap' merge into one session.
"""
import asyncio
import json
import threading
import time
from datetime import datetime

from . import adguard, alerts, db
from . import devices as D
from . import settings_store as S
from .catalog_defaults import DEFAULT_SERVICES
from .state import STATUS
from .timeutil import buckets, range_bounds

# ------------------------------------------------------------------ service catalog
_matcher_lock = threading.Lock()
_matcher: dict | None = None


def seed_services() -> None:
    if db.val("SELECT COUNT(*) FROM services"):
        return
    if S.get("catalog_seeded"):
        return
    db.exmany("INSERT OR IGNORE INTO services(name, category, domains, track_time) VALUES(?,?,?,?)",
              [(n, c, json.dumps(d), t) for n, c, d, t in DEFAULT_SERVICES])
    S.set("catalog_seeded", True)


def invalidate_matcher() -> None:
    global _matcher
    with _matcher_lock:
        _matcher = None


def _get_matcher() -> dict:
    global _matcher
    with _matcher_lock:
        if _matcher is None:
            m = {}
            for s in db.q("SELECT id, domains FROM services"):
                for dom in db.jload(s["domains"], []):
                    dom = dom.strip().lower().lstrip("*.").rstrip(".")
                    if dom:
                        m[dom] = s["id"]
            _matcher = m
        return _matcher


def match_service(domain: str) -> int | None:
    """Longest-suffix match, so music.youtube.com beats youtube.com."""
    m = _get_matcher()
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        sid = m.get(".".join(parts[i:]))
        if sid:
            return sid
    return None


def rematch_recent(days: int = 30) -> None:
    """Re-label stored queries after the catalog changes (doesn't rebuild old sessions)."""
    since = time.time() - days * 86400
    rows = db.q("SELECT id, domain FROM dns_queries WHERE ts>?", (since,))
    with db.transaction() as c:
        c.executemany("UPDATE dns_queries SET service_id=? WHERE id=?",
                      [(match_service(r["domain"] or ""), r["id"]) for r in rows])


# ------------------------------------------------------------------ ingestion
def parse_ts_ns(s: str) -> int:
    main, rest = s[:19], s[19:]
    frac = ""
    if rest.startswith("."):
        i = 1
        while i < len(rest) and rest[i].isdigit():
            i += 1
        frac, rest = rest[1:i], rest[i:]
    tz = rest or "+00:00"
    if tz == "Z":
        tz = "+00:00"
    dt = datetime.fromisoformat(main + tz)
    return int(dt.timestamp()) * 1_000_000_000 + int((frac + "000000000")[:9])


def _ip_map() -> dict[str, int]:
    m = {r["ip"]: r["device_id"] for r in db.q("SELECT ip, device_id FROM device_ips")}
    for r in db.q("SELECT id, ip FROM devices WHERE ip IS NOT NULL"):
        m[r["ip"]] = r["id"]
    return m


async def ingest() -> int:
    cursor = S.get("adguard_cursor_ns") or 0
    page = S.get("adguard_page_size")
    max_pages = 20 if cursor else 4
    collected: list[tuple[int, dict]] = []
    older, pages = None, 0
    while pages < max_pages:
        data = await adguard.querylog(page, older)
        items = (data or {}).get("data") or []
        if not items:
            break
        reached = False
        for it in items:
            try:
                ns = parse_ts_ns(it["time"])
            except Exception:
                continue
            if ns <= cursor:
                reached = True
                break
            collected.append((ns, it))
        older = (data or {}).get("oldest")
        pages += 1
        if reached or not older:
            break
    if not collected:
        return 0
    collected.sort(key=lambda x: x[0])
    _process(collected)
    S.set("adguard_cursor_ns", collected[-1][0])
    return len(collected)


def _process(items: list[tuple[int, dict]]) -> None:
    types = {t.strip().upper() for t in (S.get("usage_query_types") or "").split(",") if t.strip()}
    gap = S.get("usage_session_gap_min") * 60
    ip_map = _ip_map()
    now = time.time()
    rows, last_dns, paused_hits = [], {}, set()
    open_sessions: dict[tuple[int, int], dict] = {}
    paused = {d["id"] for d in db.q("SELECT * FROM devices") if D.is_paused(d, now)}

    for ns, it in items:
        q = it.get("question") or {}
        domain = (q.get("name") or q.get("unicode_name") or "").lower().rstrip(".")
        qtype = (q.get("type") or "").upper()
        client = it.get("client") or ""
        reason = it.get("reason") or ""
        blocked = int(reason.startswith("Filtered") and reason != "FilteredSafeSearch")
        ts = ns / 1e9
        device_id = ip_map.get(client)
        if device_id:
            last_dns[device_id] = max(last_dns.get(device_id, 0), ts)
            if device_id in paused:
                paused_hits.add(device_id)
        if types and qtype not in types:
            continue
        sid = match_service(domain) if domain else None
        rows.append((ts, client, device_id, domain, qtype, blocked, reason, sid))
        if not (device_id and sid) or blocked:
            continue
        key = (device_id, sid)
        sess = open_sessions.get(key)
        if sess is None:
            sess = db.q1("SELECT id, end, queries FROM usage_sessions WHERE device_id=? AND service_id=? "
                         "ORDER BY end DESC LIMIT 1", key) or None
        if sess and ts - sess["end"] <= gap:
            sess["end"] = max(sess["end"], ts)
            sess["queries"] += 1
            sess["dirty"] = True
        else:
            cur = db.ex("INSERT INTO usage_sessions(device_id, service_id, start, end, queries) VALUES(?,?,?,?,1)",
                        (device_id, sid, ts, ts))
            sess = {"id": cur.lastrowid, "end": ts, "queries": 1}
        open_sessions[key] = sess

    with db.transaction() as c:
        c.executemany("INSERT INTO dns_queries(ts, client, device_id, domain, qtype, blocked, reason, service_id) "
                      "VALUES(?,?,?,?,?,?,?,?)", rows)
        for s in open_sessions.values():
            if s.get("dirty"):
                c.execute("UPDATE usage_sessions SET end=?, queries=? WHERE id=?", (s["end"], s["queries"], s["id"]))
        for did, ts in last_dns.items():
            c.execute("UPDATE devices SET last_dns=MAX(IFNULL(last_dns,0), ?) WHERE id=?", (ts, did))

    # Devices talking to DNS are online, even if they skipped the last scan.
    window = S.get("dns_online_window_min") * 60
    for did, ts in last_dns.items():
        if now - ts < window:
            d = D.get(did)
            if d and not d["is_online"]:
                db.ex("UPDATE devices SET is_online=1, missed_scans=0, last_seen=? WHERE id=?", (ts, did))
                db.ex("INSERT INTO presence(device_id, start) VALUES(?, ?)", (did, ts))

    if S.get("alert_paused_activity"):
        for did in paused_hits:
            if not alerts.recent_exists("paused_activity", did, 1800):
                d = D.get(did)
                if d:
                    alerts.add("paused_activity", f"{D.display_name(d)} is trying to go online while paused",
                               "Its requests are being blocked.", level="info", device_id=did)


def cleanup() -> None:
    now = time.time()
    db.ex("DELETE FROM dns_queries WHERE ts<?", (now - S.get("retention_queries_days") * 86400,))
    keep = now - S.get("retention_sessions_days") * 86400
    db.ex("DELETE FROM usage_sessions WHERE end<?", (keep,))
    db.ex("DELETE FROM presence WHERE end IS NOT NULL AND end<?", (keep,))
    db.ex("DELETE FROM alerts WHERE ts<?", (keep,))


# ------------------------------------------------------------------ reporting
def _sessions(lo: float, hi: float, device_id: int | None = None) -> list[dict]:
    sql = ("SELECT us.*, s.name AS service, s.category, s.track_time FROM usage_sessions us "
           "JOIN services s ON s.id=us.service_id WHERE us.end>=? AND us.start<?")
    params: list = [lo - 3600, hi]
    if device_id:
        sql += " AND us.device_id=?"
        params.append(device_id)
    return db.q(sql, params)


def _clip(s: dict, lo: float, hi: float, pad: float) -> float:
    return max(0.0, min(s["end"] + pad, hi) - max(s["start"], lo))


def summary(range_key: str, device_id: int | None = None, include_system: bool = False) -> dict:
    lo, hi, kind = range_bounds(range_key)
    pad = S.get("usage_min_session_sec")
    sess = _sessions(lo, hi, device_id)
    by_service, by_device, by_category = {}, {}, {}
    total = 0.0
    for s in sess:
        if not s["track_time"] and not include_system:
            continue
        sec = _clip(s, lo, hi, pad)
        if sec <= 0:
            continue
        total += sec
        a = by_service.setdefault(s["service_id"], {"service_id": s["service_id"], "service": s["service"],
                                                      "category": s["category"], "seconds": 0, "sessions": 0})
        a["seconds"] += sec
        a["sessions"] += 1
        b = by_device.setdefault(s["device_id"], {"device_id": s["device_id"], "seconds": 0, "top": {}})
        b["seconds"] += sec
        b["top"][s["service"]] = b["top"].get(s["service"], 0) + sec
        by_category[s["category"]] = by_category.get(s["category"], 0) + sec

    names = {d["id"]: D.display_name(d) for d in db.q("SELECT * FROM devices")}
    devices_out = []
    for b in sorted(by_device.values(), key=lambda x: -x["seconds"]):
        top = sorted(b["top"].items(), key=lambda x: -x[1])[:3]
        devices_out.append({"device_id": b["device_id"], "device": names.get(b["device_id"], "Unknown"),
                            "seconds": round(b["seconds"]), "top": [{"service": n, "seconds": round(v)} for n, v in top]})

    timeline = []
    for blo, bhi, label in buckets(lo, hi, kind):
        sec = sum(_clip(s, blo, bhi, pad) for s in sess if include_system or s["track_time"])
        timeline.append({"label": label, "start": blo, "minutes": round(sec / 60, 1)})

    return {
        "range": range_key, "start": lo, "end": hi,
        "total_seconds": round(total),
        "services": sorted(({**v, "seconds": round(v["seconds"])} for v in by_service.values()),
                           key=lambda x: -x["seconds"]),
        "devices": devices_out,
        "categories": sorted(({"category": k, "seconds": round(v)} for k, v in by_category.items()),
                             key=lambda x: -x["seconds"]),
        "timeline": timeline,
    }


def recent_sessions(range_key: str, device_id: int | None = None, limit: int = 200) -> list[dict]:
    lo, hi, _ = range_bounds(range_key)
    pad = S.get("usage_min_session_sec")
    sql = ("SELECT us.*, s.name AS service, s.category, s.track_time FROM usage_sessions us "
           "JOIN services s ON s.id=us.service_id WHERE us.end>=? AND us.start<?")
    params: list = [lo, hi]
    if device_id:
        sql += " AND us.device_id=?"
        params.append(device_id)
    sql += " AND s.track_time=1 ORDER BY us.end DESC LIMIT ?"
    params.append(limit)
    names = {d["id"]: D.display_name(d) for d in db.q("SELECT * FROM devices")}
    return [{"id": r["id"], "device_id": r["device_id"], "device": names.get(r["device_id"], "Unknown"),
             "service": r["service"], "category": r["category"], "start": r["start"], "end": r["end"],
             "seconds": round(r["end"] - r["start"] + pad), "queries": r["queries"]}
            for r in db.q(sql, params)]


def top_domains(range_key: str, device_id: int | None = None, unmapped_only: bool = False, limit: int = 100) -> list[dict]:
    lo, hi, _ = range_bounds(range_key)
    sql = ("SELECT q.domain, COUNT(*) AS queries, SUM(q.blocked) AS blocked, MAX(q.ts) AS last, "
           "q.service_id, s.name AS service FROM dns_queries q LEFT JOIN services s ON s.id=q.service_id "
           "WHERE q.ts>=? AND q.ts<?")
    params: list = [lo, hi]
    if device_id:
        sql += " AND q.device_id=?"
        params.append(device_id)
    if unmapped_only:
        sql += " AND q.service_id IS NULL"
    sql += " GROUP BY q.domain ORDER BY queries DESC LIMIT ?"
    params.append(limit)
    return db.q(sql, params)


def query_counts(range_key: str) -> dict:
    lo, hi, _ = range_bounds(range_key)
    r = db.q1("SELECT COUNT(*) AS total, IFNULL(SUM(blocked),0) AS blocked FROM dns_queries WHERE ts>=? AND ts<?", (lo, hi))
    return r or {"total": 0, "blocked": 0}


def presence_timeline(device_id: int, range_key: str) -> list[dict]:
    lo, hi, _ = range_bounds(range_key)
    now = time.time()
    rows = db.q("SELECT start, end FROM presence WHERE device_id=? AND IFNULL(end, ?)>=? AND start<? ORDER BY start",
                (device_id, now, lo, hi))
    return [{"start": max(r["start"], lo), "end": min(r["end"] or now, hi), "open": r["end"] is None} for r in rows]


_ingest_lock: asyncio.Lock | None = None


def reset_lock() -> None:
    global _ingest_lock
    _ingest_lock = asyncio.Lock()


async def sync_loop_once() -> int:
    if _ingest_lock is None:
        reset_lock()
    async with _ingest_lock:
        n = await ingest()
    STATUS["adguard"]["ingested"] += n
    return n
