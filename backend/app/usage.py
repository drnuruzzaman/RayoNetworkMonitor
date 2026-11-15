"""Turns the AdGuard DNS log into per-device app usage.

Screen time is an estimate. When a device keeps looking up an app's domains, it's treated as
using that app. Lookups closer together than the 'session gap' merge into one session.
"""
import asyncio
import json
import re
import threading
import time
from datetime import datetime

from . import activity, adguard, alerts, db
from . import devices as D
from . import settings_store as S
from .catalog_defaults import CATALOG_ADDED_IN, CATALOG_VERSION, DEFAULT_SERVICES
from .state import STATUS
from .timeutil import buckets, range_bounds

# ------------------------------------------------------------------ service catalog
_matcher_lock = threading.Lock()
_matcher: dict | None = None


_APP_FIELDS = ("category", "domains", "track_time", "hidden", "source", "reviewed", "adguard_id", "registrable")


def catalog_snapshot() -> list[dict]:
    """The whole 'Apps & categories' list, as saved in defaults / export files."""
    return [{"id": r["id"], "name": r["name"], "category": r["category"], "domains": db.jload(r["domains"], []),
             "track_time": bool(r["track_time"]), "hidden": bool(r["hidden"]), "source": r["source"] or "user",
             "reviewed": bool(r["reviewed"] if r["reviewed"] is not None else 1), "adguard_id": r["adguard_id"],
             "registrable": r["registrable"]}
            for r in db.q("SELECT * FROM services ORDER BY name COLLATE NOCASE")]


def _match_apps(apps: list[dict]) -> tuple[dict[int, dict], list[dict], list[dict]]:
    """Pair each saved app with an existing one: same name first, else same id (e.g. renamed since).
    Returns ({existing id: saved app}, saved apps with no match, existing apps not in the saved list)."""
    cur = catalog_snapshot()
    by_name = {c["name"].lower(): c for c in cur}
    by_id = {c["id"]: c for c in cur}
    paired: dict[int, dict] = {}
    new = []
    for a in apps:
        c = by_name.get(a["name"].lower())
        if c is None and a.get("id") in by_id and by_id[a["id"]]["name"].lower() not in {x["name"].lower() for x in apps}:
            c = by_id[a["id"]]
        if c is not None and c["id"] not in paired:
            paired[c["id"]] = a
        else:
            new.append(a)
    extra = [c for c in cur if c["id"] not in paired]
    return paired, new, extra


def catalog_diff(apps: list[dict]) -> dict:
    """What applying a saved app list would change: names to add, update and remove."""
    paired, new, extra = _match_apps(apps)
    cur = {c["id"]: c for c in catalog_snapshot()}
    changed = [a["name"] for cid, a in paired.items()
               if a["name"] != cur[cid]["name"] or any(a[f] != cur[cid][f] for f in _APP_FIELDS)]
    return {"add": sorted(a["name"] for a in new), "update": sorted(changed), "remove": sorted(c["name"] for c in extra)}


def apply_catalog(apps: list[dict]) -> dict:
    """Make 'Apps & categories' match a saved list. Existing apps are updated in place (keeping their history,
    limits and schedules); apps not in the list are removed. Past lookups are re-labelled."""
    diff = catalog_diff(apps)
    paired, new, extra = _match_apps(apps)
    now = time.time()
    with db.transaction() as c:
        for cid in (x["id"] for x in extra):
            c.execute("DELETE FROM services WHERE id=?", (cid,))
        for cid in paired:  # temporary names, so swapped/renamed apps never clash on the unique name
            c.execute("UPDATE services SET name=? WHERE id=?", (f"\x00homenet-rename-{cid}", cid))
        for cid, a in paired.items():
            c.execute("UPDATE services SET name=?, category=?, domains=?, track_time=?, hidden=?, source=?, reviewed=?, "
                      "adguard_id=?, registrable=? WHERE id=?",
                      (a["name"], a["category"], json.dumps(a["domains"]), int(a["track_time"]), int(a["hidden"]),
                       a["source"], int(a["reviewed"]), a["adguard_id"], a["registrable"], cid))
        for a in new:
            c.execute("INSERT INTO services(name, category, domains, track_time, hidden, source, reviewed, adguard_id, "
                      "registrable, created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (a["name"], a["category"], json.dumps(a["domains"]), int(a["track_time"]), int(a["hidden"]),
                       a["source"], int(a["reviewed"]), a["adguard_id"], a["registrable"], now))
    if any(diff.values()):
        invalidate_matcher()
        rematch_recent()
        touched = {r["id"] for r in db.q("SELECT id FROM services WHERE name IN ({})".format(
            ",".join("?" * len(diff["add"] + diff["update"]))), diff["add"] + diff["update"])} if diff["add"] + diff["update"] else set()
        for sid in touched:
            rebuild_sessions(sid)
    return diff


def seed_services() -> list[int]:
    """First run: load your saved app list if there is one, else the whole starter catalog. Later versions: add
    only the newly introduced apps. Returns ids of services added (so their past sessions can be rebuilt)."""
    if not S.get("catalog_seeded") and not db.val("SELECT COUNT(*) FROM services"):
        own = S.saved_defaults().get("apps")
        if own:
            apply_catalog(own)
        else:
            db.exmany("INSERT OR IGNORE INTO services(name, category, domains, track_time, source, reviewed) VALUES(?,?,?,?,'builtin',1)",
                      [(n, c, json.dumps(d), t) for n, c, d, t in DEFAULT_SERVICES])
        S.set("catalog_seeded", True)
        S.set("catalog_version", CATALOG_VERSION)
        return []
    have = S.get("catalog_version") or 1
    added: list[int] = []
    for ver in range(have + 1, CATALOG_VERSION + 1):
        names = CATALOG_ADDED_IN.get(ver, set())
        for n, c, d, t in DEFAULT_SERVICES:
            if n in names and not db.q1("SELECT 1 FROM services WHERE name=?", (n,)):
                cur = db.ex("INSERT INTO services(name, category, domains, track_time, source, reviewed) VALUES(?,?,?,?,'builtin',1)",
                            (n, c, json.dumps(d), t))
                added.append(cur.lastrowid)
    S.set("catalog_version", CATALOG_VERSION)
    if added:
        invalidate_matcher()
        rematch_recent()
        for sid in added:
            rebuild_sessions(sid)
    return added


def apply_new_apps(service_ids: list[int]) -> None:
    """After apps are added (auto-detected or synced): label stored lookups and rebuild their sessions."""
    if not service_ids:
        return
    invalidate_matcher()
    for sid in service_ids:
        row = db.q1("SELECT domains FROM services WHERE id=?", (sid,))
        if not row:
            continue
        for dom in db.jload(row["domains"], []):
            like = dom.replace("*", "%")  # instagram.*.fbcdn.net → instagram.%.fbcdn.net
            db.ex("UPDATE dns_queries SET service_id=? WHERE service_id IS NULL AND (domain LIKE ? OR domain LIKE ?)",
                  (sid, like, "%." + like))
        rebuild_sessions(sid)


def rebuild_sessions(service_id: int) -> int:
    """Recreate an app's usage sessions from stored lookups, so a new or edited app also covers the past."""
    gap = S.get("usage_session_gap_min") * 60
    rows = db.q("SELECT device_id, ts FROM dns_queries WHERE service_id=? AND device_id IS NOT NULL AND blocked=0 "
                "ORDER BY device_id, ts", (service_id,))
    sessions, cur = [], None
    for r in rows:
        if cur and cur[0] == r["device_id"] and r["ts"] - cur[2] <= gap:
            cur[2] = r["ts"]
            cur[3] += 1
        else:
            if cur:
                sessions.append(tuple(cur))
            cur = [r["device_id"], r["ts"], r["ts"], 1]
    if cur:
        sessions.append(tuple(cur))
    with db.transaction() as c:
        c.execute("DELETE FROM usage_sessions WHERE service_id=?", (service_id,))
        c.executemany("INSERT INTO usage_sessions(device_id, service_id, start, end, queries) VALUES(?,?,?,?,?)",
                      [(d, service_id, s, e, n) for d, s, e, n in sessions])
    return len(sessions)


def invalidate_matcher() -> None:
    global _matcher
    with _matcher_lock:
        _matcher = None


def _wildcard(dom: str) -> tuple[re.Pattern, int] | None:
    """'instagram.*.fbcdn.net' → regex for it (and its sub-addresses), plus how specific it is (literal characters).
    None if the pattern is too vague to be safe (fewer than two literal labels, e.g. 'instagram.*')."""
    if len([p for p in dom.split(".") if p and "*" not in p]) < 2:
        return None
    body = ".".join("[^.]+" if p == "*" else re.escape(p).replace(r"\*", "[^.]*") for p in dom.split("."))
    # A lone '*' label may stand for several labels (instagram.*.fbcdn.net matches instagram.fsyd3-2.fna.fbcdn.net).
    body = body.replace(r"[^.]+", r"[^.]+(?:\.[^.]+)*")
    return re.compile(rf"^(?:.+\.)?{body}$"), len(dom.replace("*", ""))


def _get_matcher() -> dict:
    global _matcher
    with _matcher_lock:
        if _matcher is None:
            exact, wild = {}, []
            # Lower priority first, so for the same address a user/built-in app beats AdGuard's, which beats auto-detected.
            for s in db.q("SELECT id, domains FROM services ORDER BY CASE source WHEN 'auto' THEN 0 "
                          "WHEN 'adguard' THEN 1 ELSE 2 END, id"):
                for dom in db.jload(s["domains"], []):
                    dom = dom.strip().lower().lstrip("*.").rstrip(".")
                    if not dom:
                        continue
                    if "*" in dom:
                        w = _wildcard(dom)
                        if w:
                            wild.append((w[0], w[1], s["id"]))
                    else:
                        exact[dom] = s["id"]
            _matcher = {"exact": exact, "wild": wild}
        return _matcher


def match_service(domain: str) -> int | None:
    """Most specific match wins: longest matching suffix (music.youtube.com beats youtube.com), or a wildcard
    entry with more literal characters (instagram.*.fbcdn.net beats fbcdn.net). On a tie the exact entry wins."""
    m = _get_matcher()
    domain = (domain or "").lower()
    best, best_len = None, 0
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        key = ".".join(parts[i:])
        sid = m["exact"].get(key)
        if sid:
            best, best_len = sid, len(key)
            break
    wild_sid, wild_len = None, 0
    for rx, lit, sid in m["wild"]:  # in priority order, so a later (higher priority) entry wins a tie
        if lit >= wild_len and rx.match(domain):
            wild_sid, wild_len = sid, lit
    return wild_sid if wild_sid and wild_len > best_len else best


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


# ------------------------------------------------------------------ why was it blocked?
_lists_cache: dict = {"ts": 0.0, "names": {}}


async def _list_names() -> dict[int, str]:
    if time.time() - _lists_cache["ts"] > 600:
        try:
            st = await adguard.filtering_status()
            names = {f.get("id"): f.get("name") for f in (st.get("filters") or []) + (st.get("whitelist_filters") or [])}
            _lists_cache.update(ts=time.time(), names=names)
        except Exception:
            pass
    return _lists_cache["names"]


def classify_block(it: dict, list_names: dict) -> tuple[str | None, str | None]:
    """(source, detail) for a blocked AdGuard log entry, or (None, None) if it wasn't blocked."""
    reason = it.get("reason") or ""
    if not reason.startswith("Filtered") or reason == "FilteredSafeSearch":
        return None, None
    if reason == "FilteredBlockedService":
        return "app", it.get("service_name") or None
    if reason == "FilteredParental":
        return "adult", None
    if reason in ("FilteredSafeBrowsing", "FilteredBlackListSafeBrowsing"):
        return "malware", None
    rules = it.get("rules") or ([{"text": it.get("rule"), "filter_list_id": it.get("filterId")}] if it.get("rule") else [])
    for r in rules:
        text, fid = r.get("text") or "", r.get("filter_list_id")
        if fid == 0 and "$client=" in text and ",important" in text:
            return ("pause", None) if text.startswith("||*^") else ("limit", None)
        if fid == 0:
            return "custom", text[:200]
        if fid is not None:
            return "filter", list_names.get(fid) or f"Filter list {fid}"
    return "other", reason


async def backfill_block_sources() -> int:
    """One-off: label blocked lookups stored before HomeNet recorded the reason (uses AdGuard's log)."""
    if S.get("block_source_backfilled"):
        return 0
    names = await _list_names()
    updates, older = [], None
    for _ in range(20):
        params = {"limit": 1000, "response_status": "blocked"}
        if older:
            params["older_than"] = older
        data = await adguard.request("GET", "/querylog", params=params, timeout=30)
        items = (data or {}).get("data") or []
        for it in items:
            src, detail = classify_block(it, names)
            if src:
                try:
                    ts = parse_ts_ns(it["time"]) / 1e9
                except Exception:
                    continue
                dom = ((it.get("question") or {}).get("name") or "").lower().rstrip(".")
                updates.append((src, detail, ts, it.get("client") or "", dom))
        older = (data or {}).get("oldest")
        if not items or not older:
            break
    with db.transaction() as c:
        c.executemany("UPDATE dns_queries SET block_source=?, block_detail=? WHERE ts=? AND client=? AND domain=? "
                      "AND blocked=1 AND block_source IS NULL", updates)
    S.set("block_source_backfilled", True)
    return len(updates)


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
    _process(collected, await _list_names())
    S.set("adguard_cursor_ns", collected[-1][0])
    return len(collected)


def _process(items: list[tuple[int, dict]], list_names: dict | None = None) -> None:
    list_names = list_names or {}
    types = {t.strip().upper() for t in (S.get("usage_query_types") or "").split(",") if t.strip()}
    gap = S.get("usage_session_gap_min") * 60
    ip_map = _ip_map()
    now = time.time()
    rows, last_dns, paused_hits = [], {}, set()
    open_sessions: dict[tuple[int, int], dict] = {}
    paused = {d["id"] for d in db.q("SELECT * FROM devices") if D.is_paused(d, now)}
    gateway_ids = {r["id"] for r in db.q("SELECT id FROM devices WHERE is_gateway=1")}
    unknown: list[tuple] = []

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
        src, detail = classify_block(it, list_names) if blocked else (None, None)
        rows.append((ts, client, device_id, domain, qtype, blocked, reason, sid, src, detail))
        if sid is None and domain:
            unknown.append((ts, domain, device_id, blocked, device_id in gateway_ids))
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
        c.executemany("INSERT INTO dns_queries(ts, client, device_id, domain, qtype, blocked, reason, service_id, "
                      "block_source, block_detail) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        for s in open_sessions.values():
            if s.get("dirty"):
                c.execute("UPDATE usage_sessions SET end=?, queries=? WHERE id=?", (s["end"], s["queries"], s["id"]))
        for did, ts in last_dns.items():
            c.execute("UPDATE devices SET last_dns=MAX(IFNULL(last_dns,0), ?) WHERE id=?", (ts, did))

    # Automatic app detection for addresses no app covers yet.
    if unknown and S.get("auto_detect_apps"):
        from . import detect
        try:
            detect.note_unknown(unknown)
            apply_new_apps(detect.promote_ready())
        except Exception:
            import logging
            logging.getLogger("homenet").exception("auto-detect failed")

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
           "JOIN services s ON s.id=us.service_id WHERE us.end>=? AND us.start<?" + _MINOR_VISIT_SQL)
    params: list = [lo - 3600, hi, S.get("auto_min_session_lookups")]
    if device_id:
        sql += " AND us.device_id=?"
        params.append(device_id)
    return db.q(sql, params)


# Quick check-ins to auto-detected sites (fewer lookups than the setting) aren't screen time.
_MINOR_VISIT_SQL = " AND NOT (IFNULL(s.source,'') = 'auto' AND us.queries < ?)"


def _clip(s: dict, lo: float, hi: float, pad: float) -> float:
    return max(0.0, min(s["end"] + pad, hi) - max(s["start"], lo))


def _session_seconds(s: dict, lo: float, hi: float, pad: float, act: dict | None) -> float:
    """App time for one session. With activity detection on, only the part while someone was using the device."""
    a, b = max(s["start"], lo), min(s["end"] + pad, hi)
    if b <= a:
        return 0.0
    if act is None:
        return b - a
    return activity.overlap(a, b, act.get(s["device_id"], []))


def summary(range_key: str, device_id: int | None = None, include_system: bool = False) -> dict:
    lo, hi, kind = range_bounds(range_key)
    pad = S.get("usage_min_session_sec")
    sess = _sessions(lo, hi, device_id)
    act = activity.active_intervals(lo, hi, device_id) if S.get("activity_detection") else None
    by_service, by_device, by_category = {}, {}, {}
    for s in sess:
        if not s["track_time"] and not include_system:
            continue
        sec = _session_seconds(s, lo, hi, pad, act)
        if sec <= 0:
            continue
        a = by_service.setdefault(s["service_id"], {"service_id": s["service_id"], "service": s["service"],
                                                      "category": s["category"], "seconds": 0, "sessions": 0})
        a["seconds"] += sec
        a["sessions"] += 1
        b = by_device.setdefault(s["device_id"], {"device_id": s["device_id"], "seconds": 0, "top": {}})
        b["seconds"] += sec
        b["top"][s["service"]] = b["top"].get(s["service"], 0) + sec
        by_category[s["category"]] = by_category.get(s["category"], 0) + sec

    if act is not None:
        # A device's screen time is the time someone was using it, not the sum of its apps
        # (apps running side by side would otherwise be counted twice).
        for did, ivs in act.items():
            by_device.setdefault(did, {"device_id": did, "seconds": 0, "top": {}})["seconds"] = activity.total(ivs)
        by_device = {k: v for k, v in by_device.items() if k in act}
    total = sum(b["seconds"] for b in by_device.values())

    names = {d["id"]: D.display_name(d) for d in db.q("SELECT * FROM devices")}
    devices_out = []
    for b in sorted(by_device.values(), key=lambda x: -x["seconds"]):
        top = sorted(b["top"].items(), key=lambda x: -x[1])[:3]
        devices_out.append({"device_id": b["device_id"], "device": names.get(b["device_id"], "Unknown"),
                            "seconds": round(b["seconds"]), "top": [{"service": n, "seconds": round(v)} for n, v in top]})

    timeline = []
    for blo, bhi, label in buckets(lo, hi, kind):
        if act is not None:
            sec = sum(activity.overlap(blo, bhi, ivs) for ivs in act.values())
        else:
            sec = sum(_clip(s, blo, bhi, pad) for s in sess if include_system or s["track_time"])
        timeline.append({"label": label, "start": blo, "minutes": round(sec / 60, 1)})

    return {
        "range": range_key, "start": lo, "end": hi,
        "activity_detection": act is not None,
        "total_seconds": round(total),
        "services": sorted(({**v, "seconds": round(v["seconds"])} for v in by_service.values()),
                           key=lambda x: -x["seconds"]),
        "devices": devices_out,
        "categories": sorted(({"category": k, "seconds": round(v)} for k, v in by_category.items()),
                             key=lambda x: -x["seconds"]),
        "timeline": timeline,
    }


def screentime(device_id: int | None, period: str = "week", date: str | None = None, service_id: int | None = None) -> dict:
    """Apple-style Screen Time: per-day (week) or per-hour (day) totals split by category, plus most-used apps.

    Totals are the time someone was actually using the device. Each bucket's in-use time is split across
    categories by how its apps overlapped it. Time not covered by a known app is "Other"."""
    from datetime import datetime, timedelta
    day = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
    day = day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone()
    if period == "day":
        lo_dt, hi_dt = day, day + timedelta(days=1)
        edges = [lo_dt + timedelta(hours=h) for h in range(25)]
        labels = [f"{h:02d}" for h in range(24)]
        prev = (lo_dt - timedelta(days=1), lo_dt)
    else:
        lo_dt = day - timedelta(days=day.weekday())  # Monday
        hi_dt = lo_dt + timedelta(days=7)
        edges = [lo_dt + timedelta(days=i) for i in range(8)]
        labels = [(lo_dt + timedelta(days=i)).strftime("%a") for i in range(7)]
        prev = (lo_dt - timedelta(days=7), lo_dt)
    lo, hi = lo_dt.timestamp(), hi_dt.timestamp()
    now = time.time()
    pad = S.get("usage_min_session_sec")
    act = activity.active_intervals(lo, min(hi, now), device_id) if S.get("activity_detection") else None
    sess = [s for s in _sessions(lo, hi, device_id) if s["track_time"]]
    if device_id is None:
        non_human = activity.non_human_device_ids()
        sess = [s for s in sess if s["device_id"] not in non_human]

    buckets, cat_tot, app_tot = [], {}, {}
    for i in range(len(edges) - 1):
        blo, bhi = edges[i].timestamp(), edges[i + 1].timestamp()
        if act is not None:
            active = sum(activity.overlap(blo, bhi, ivs) for ivs in act.values())
        else:
            active = None
        cats, apps = {}, {}
        for s in sess:
            a, b = max(s["start"], blo), min(s["end"] + pad, bhi)
            if b <= a:
                continue
            sec = activity.overlap(a, b, act.get(s["device_id"], [])) if act is not None else b - a
            if sec > 0:
                cats[s["category"]] = cats.get(s["category"], 0) + sec
                key = (s["service_id"], s["service"], s["category"])
                apps[key] = apps.get(key, 0) + sec
        attributed = sum(cats.values())
        if active is None:
            active = attributed
        if attributed > active > 0:            # apps running side by side: scale to real in-use time
            k = active / attributed
            cats = {c: v * k for c, v in cats.items()}
            apps = {a: v * k for a, v in apps.items()}
        elif active > attributed:
            cats["Other"] = cats.get("Other", 0) + (active - attributed)
        for c, v in cats.items():
            cat_tot[c] = cat_tot.get(c, 0) + v
        for a, v in apps.items():
            app_tot[a] = app_tot.get(a, 0) + v
        buckets.append({"label": labels[i], "start": blo, "date": edges[i].strftime("%Y-%m-%d"),
                        "seconds": round(active), "future": blo > now,
                        "categories": {c: round(v) for c, v in cats.items() if v >= 1},
                        "apps": {str(a[0]): round(v) for a, v in apps.items() if v >= 1}})

    total = sum(b["seconds"] for b in buckets)
    # Previous period for the "% from last week" comparison.
    p_act = activity.active_intervals(prev[0].timestamp(), prev[1].timestamp(), device_id) if act is not None else {}
    prev_total = sum(activity.total(v) for v in p_act.values())
    days_so_far = max(1, sum(1 for b in buckets if b["seconds"] > 0)) if period != "day" else 1  # days with data
    return {
        "period": period, "start": lo, "end": hi, "label": (lo_dt.strftime("%a %d %b") if period == "day"
                                                            else f"{lo_dt.strftime('%d %b')} – {(hi_dt - timedelta(days=1)).strftime('%d %b')}"),
        "total_seconds": total,
        "average_seconds": round(total / days_so_far) if period != "day" else total,
        "previous_seconds": round(prev_total),
        "buckets": buckets,
        "categories": sorted(({"category": c, "seconds": round(v)} for c, v in cat_tot.items() if v >= 30), key=lambda x: -x["seconds"]),
        "apps": sorted(({"service_id": sid, "service": a, "category": c, "seconds": round(v)} for (sid, a, c), v in app_tot.items() if v >= 30),
                       key=lambda x: -x["seconds"])[:25],
        "is_current": lo <= now < hi,
        "app": _app_periods(sess, service_id, lo, min(hi, now), pad, act) if service_id else None,
    }


def _app_periods(sess: list[dict], service_id: int, lo: float, hi: float, pad: float, act: dict | None) -> dict:
    """When one app was used in [lo, hi]: its sessions cut to the times the device was really in use,
    joined when less than 2 minutes apart. [{start, end, seconds}], newest first."""
    pieces = []
    for s in sess:
        if s["service_id"] != service_id:
            continue
        a, b = max(s["start"], lo), min(s["end"] + pad, hi)
        if b <= a:
            continue
        if act is None:
            pieces.append((a, b))
        else:
            pieces += [(max(a, x), min(b, y)) for x, y in act.get(s["device_id"], []) if min(b, y) > max(a, x)]
    merged: list[list[float]] = []
    for a, b in sorted(pieces):
        if merged and a - merged[-1][1] <= 120:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return {"service_id": service_id,
            "periods": [{"start": a, "end": b, "seconds": round(b - a)} for a, b in reversed(merged) if b - a >= 1]}


def recent_sessions(range_key: str, device_id: int | None = None, limit: int = 200) -> list[dict]:
    lo, hi, _ = range_bounds(range_key)
    pad = S.get("usage_min_session_sec")
    sql = ("SELECT us.*, s.name AS service, s.category, s.track_time FROM usage_sessions us "
           "JOIN services s ON s.id=us.service_id WHERE us.end>=? AND us.start<?" + _MINOR_VISIT_SQL)
    params: list = [lo, hi, S.get("auto_min_session_lookups")]
    if device_id:
        sql += " AND us.device_id=?"
        params.append(device_id)
    sql += " AND s.track_time=1 ORDER BY us.end DESC LIMIT ?"
    params.append(limit * 3)
    names = {d["id"]: D.display_name(d) for d in db.q("SELECT * FROM devices")}
    act = activity.active_intervals(lo, hi, device_id) if S.get("activity_detection") else None
    out = []
    for r in db.q(sql, params):
        sec = _session_seconds(r, lo, hi, pad, act)
        if sec <= 0:
            continue  # only background traffic while nobody was using the device
        out.append({"id": r["id"], "device_id": r["device_id"], "device": names.get(r["device_id"], "Unknown"),
                    "service_id": r["service_id"], "service": r["service"], "category": r["category"],
                    "start": r["start"], "end": r["end"], "seconds": round(sec), "queries": r["queries"]})
        if len(out) >= limit:
            break
    return out


def _in_use_filter(lo: float, hi: float, device_id: int | None) -> tuple[str, list] | None:
    """SQL condition limiting lookups to periods when someone was using the device. None = nothing in use."""
    act = activity.active_intervals(lo, hi, device_id)
    parts, params = [], []
    for did, ivs in act.items():
        for s, e in ivs:
            parts.append("(q.device_id=? AND q.ts>=? AND q.ts<?)")
            params += [did, s, e]
    if not parts:
        return None
    return " AND (" + " OR ".join(parts) + ")", params


def top_domains(range_key: str, device_id: int | None = None, unmapped_only: bool = False, limit: int = 100,
                in_use_only: bool = False) -> list[dict]:
    """Most looked-up addresses. With in_use_only, only what was looked up while someone was using the
    device, leaving out background services, infrastructure and tracker blocks."""
    lo, hi, _ = range_bounds(range_key)
    where = " WHERE q.ts>=? AND q.ts<?"
    params: list = [lo, hi]
    if device_id:
        where += " AND q.device_id=?"
        params.append(device_id)
    if unmapped_only:
        where += " AND q.service_id IS NULL"
    if in_use_only and S.get("activity_detection"):
        f = _in_use_filter(lo, hi, device_id)
        if f is None:
            return []
        where += f[0] + (" AND IFNULL(q.block_source,'') != 'filter' AND (s.id IS NULL OR "
                         "(s.track_time=1 AND IFNULL(s.hidden,0)=0 AND s.category != 'System'))")
        params += f[1]
    sql = ("SELECT q.domain, COUNT(*) AS queries, SUM(q.blocked) AS blocked, MAX(q.ts) AS last, "
           "q.service_id, s.name AS service, s.category FROM dns_queries q LEFT JOIN services s ON s.id=q.service_id"
           + where + " GROUP BY q.domain ORDER BY queries DESC LIMIT ?")
    rows = db.q(sql, params + [limit * 3 if in_use_only else limit])
    if in_use_only:
        rows = [r for r in rows if not activity._is_infra(r["domain"])][:limit]
    # Why each domain's lookups were blocked: [{source, detail, count, last}]
    blocked_domains = [r["domain"] for r in rows if r["blocked"]]
    by_domain: dict[str, list] = {}
    if blocked_domains:
        marks = ",".join("?" * len(blocked_domains))
        bsql = (f"SELECT domain, IFNULL(block_source,'unknown') AS source, block_detail AS detail, COUNT(*) AS count, "
                f"MIN(ts) AS first, MAX(ts) AS last FROM dns_queries WHERE blocked=1 AND ts>=? AND ts<? AND domain IN ({marks})")
        bparams: list = [lo, hi, *blocked_domains]
        if device_id:
            bsql += " AND device_id=?"
            bparams.append(device_id)
        bsql += " GROUP BY domain, source, detail ORDER BY count DESC"
        for b in db.q(bsql, bparams):
            by_domain.setdefault(b.pop("domain"), []).append(b)
    for r in rows:
        r["blocked_by"] = by_domain.get(r["domain"], [])
    return rows


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
