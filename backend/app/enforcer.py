"""Applies pauses, schedules and per-device controls to AdGuard Home.

* Pausing internet adds a high-priority rule that blocks every lookup from that device's IP
  addresses (`||*^$client=IP,important`). The rules sit in a clearly marked block of AdGuard's
  custom rules, and anything you wrote there yourself is left alone.
* Per-device controls (blocked apps, safe search, etc.) are pushed as an AdGuard persistent client.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta

from . import adguard, db
from . import devices as D
from . import settings_store as S
from .state import STATUS

BEGIN = "! >>> HomeNet Monitor managed rules - edit in the HomeNet dashboard, not here"
END = "! <<< HomeNet Monitor managed rules"
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ------------------------------------------------------------------ schedules
def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def rule_active(rule: dict, now: datetime | None = None) -> bool:
    if not rule.get("enabled"):
        return False
    now = now or datetime.now()
    days = set(db.jload(rule["days"], []) if isinstance(rule["days"], str) else rule["days"])
    start, end = _mins(rule["start"]), _mins(rule["end"])
    t = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (now - timedelta(days=1)).weekday()
    if start == end:
        return today in days  # all day
    if start < end:
        return today in days and start <= t < end
    # Overnight window, e.g. 21:00 → 07:00
    return (today in days and t >= start) or (yesterday in days and t < end)


def active_rules() -> list[dict]:
    now = datetime.now()
    return [r for r in db.q("SELECT * FROM rules WHERE enabled=1") if rule_active(r, now)]


def device_block_state(now: float | None = None) -> dict[int, dict]:
    """device_id → {'paused': bool, 'reasons': [...], 'services': set()}"""
    now = now or time.time()
    state: dict[int, dict] = {}
    for d in db.q("SELECT * FROM devices"):
        st = {"paused": False, "reasons": [], "services": set(D.controls(d)["blocked_services"])}
        if d["paused"]:
            st["paused"] = True
            st["reasons"].append("Paused until resumed")
        elif d["paused_until"] and d["paused_until"] > now:
            st["paused"] = True
            st["reasons"].append("Paused until " + datetime.fromtimestamp(d["paused_until"]).strftime("%H:%M"))
        state[d["id"]] = st
    for r in active_rules():
        for did in db.jload(r["device_ids"], []):
            st = state.get(did)
            if not st:
                continue
            if r["action"] == "pause_internet":
                st["paused"] = True
                st["reasons"].append(f"Schedule: {r['name']}")
            elif r["action"] == "block_services":
                st["services"] |= set(db.jload(r["services"], []))
                st["reasons"].append(f"Schedule: {r['name']} (apps blocked)")
    return state


def device_ips(device_id: int) -> list[str]:
    d = D.get(device_id)
    ips = {d["ip"]} if d and d["ip"] else set()
    since = time.time() - 86400
    ips |= {r["ip"] for r in db.q("SELECT ip FROM device_ips WHERE device_id=? AND last_seen>?", (device_id, since))}
    return sorted(i for i in ips if i)


# ------------------------------------------------------------------ daily time limits
def limit_applies_today(lim: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return bool(lim["enabled"]) and now.weekday() in set(db.jload(lim["days"], []))


def limit_target(lim: dict) -> tuple[str, list[str]]:
    """(display name, addresses to block) for an app or a whole category."""
    if lim["target_type"] == "app":
        s = db.q1("SELECT name, domains FROM services WHERE id=?", (int(lim["target"]),))
        return (s["name"], db.jload(s["domains"], [])) if s else ("Removed app", [])
    rows = db.q("SELECT domains FROM services WHERE category=? AND track_time=1 AND IFNULL(hidden,0)=0", (lim["target"],))
    doms = sorted({d for r in rows for d in db.jload(r["domains"], [])})
    return lim["target"], doms


def limits_usage(device_id: int | None = None) -> list[dict]:
    """Every limit with how much of it each device has used today."""
    from . import usage
    lims = db.q("SELECT * FROM app_limits ORDER BY id")
    summaries: dict[int, dict] = {}
    out = []
    for lim in lims:
        dids = db.jload(lim["device_ids"], [])
        if device_id and device_id not in dids:
            continue
        name, domains = limit_target(lim)
        per_dev = []
        for did in dids:
            if did not in summaries:
                summaries[did] = usage.summary("today", did)
            sm = summaries[did]
            if lim["target_type"] == "app":
                used = sum(s["seconds"] for s in sm["services"] if str(s["service_id"]) == str(lim["target"]))
            else:
                used = sum(c["seconds"] for c in sm["categories"] if c["category"] == lim["target"])
            per_dev.append({"device_id": did, "used_seconds": used, "reached": used >= lim["minutes"] * 60})
        out.append({**lim, "device_ids": dids, "days": db.jload(lim["days"], []), "enabled": bool(lim["enabled"]),
                    "target_name": name, "domains": domains, "applies_today": limit_applies_today(lim), "usage": per_dev})
    return out


def app_blocks_now() -> dict[int, set[str]]:
    """device_id → addresses of the HomeNet apps it always blocks (Controls → Always block these apps)."""
    domains = {r["id"]: db.jload(r["domains"], []) for r in db.q("SELECT id, domains FROM services")}
    blocks: dict[int, set[str]] = {}
    for d in db.q("SELECT id, controls FROM devices"):
        for sid in D.controls(d).get("blocked_apps") or []:
            if domains.get(sid):
                blocks.setdefault(d["id"], set()).update(domains[sid])
    return blocks


def limit_blocks_now() -> dict[int, set[str]]:
    """device_id → addresses to block because a time limit ran out today. Alerts once per day per limit."""
    from . import alerts
    blocks: dict[int, set[str]] = {}
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    for lim in limits_usage():
        if not lim["applies_today"] or not lim["domains"]:
            continue
        for u in lim["usage"]:
            if not u["reached"]:
                continue
            blocks.setdefault(u["device_id"], set()).update(lim["domains"])
            kind = f"limit_reached:{lim['id']}"
            if not alerts.recent_exists(kind, u["device_id"], time.time() - midnight):
                d = D.get(u["device_id"])
                if d:
                    alerts.add(kind, f"{lim['target_name']} time limit reached on {D.display_name(d)}",
                               f"{lim['minutes']} minutes used. It's blocked until midnight.", level="warning",
                               device_id=u["device_id"])
    return blocks


# ------------------------------------------------------------------ AdGuard sync
async def _sync_pause_rules(paused_ids: list[int], limit_blocks: dict[int, set[str]] | None = None) -> list[str]:
    """Write HomeNet's managed block of AdGuard custom rules:
    pauses (block everything) and time limits that have run out (block that app's addresses)."""
    ips = sorted({ip for did in paused_ids for ip in device_ips(did)})
    limit_lines = []
    for did, domains in (limit_blocks or {}).items():
        if did in paused_ids:
            continue
        for ip in device_ips(did):
            limit_lines += [f"||{dom}^$client={ip},important" for dom in sorted(domains)]
    status = await adguard.filtering_status()
    rules = list(status.get("user_rules") or [])
    kept, inside = [], False
    for line in rules:
        if line.strip() == BEGIN:
            inside = True
            continue
        if line.strip() == END:
            inside = False
            continue
        if not inside:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    new = list(kept)
    if ips or limit_lines:
        new += ([""] if kept else []) + [BEGIN] + [f"||*^$client={ip},important" for ip in ips] + limit_lines + [END]
    if new != rules:
        await adguard.set_user_rules(new)
    return ips


def _client_payload(d: dict, services: set) -> dict:
    c = D.controls(d)
    ids = device_ips(d["id"])
    return {
        "ids": ids,
        "use_global_settings": bool(c["use_global"]),
        "filtering_enabled": bool(c["filtering"]),
        "parental_enabled": bool(c["parental"]),
        "safebrowsing_enabled": bool(c["safebrowsing"]),
        "safesearch": {"enabled": bool(c["safe_search"]), "bing": True, "duckduckgo": True, "google": True,
                       "pixabay": True, "yandex": True, "youtube": True},
        "use_global_blocked_services": not services,
        "blocked_services": sorted(services),
    }


def _needs_client(d: dict, services: set) -> bool:
    if d["ag_client_name"]:
        return True
    if services or D.controls(d) != D.DEFAULT_CONTROLS:
        return True
    return bool(S.get("adguard_sync_clients") and d["name"])


async def _sync_clients(state: dict[int, dict]) -> None:
    existing = None
    for d in db.q("SELECT * FROM devices"):
        services = state.get(d["id"], {}).get("services", set())
        if not _needs_client(d, services):
            continue
        payload = _client_payload(d, services)
        if not payload["ids"]:
            continue
        want_name = D.display_name(d)
        fingerprint = json.dumps({**payload, "name": want_name}, sort_keys=True)
        if d["ag_client_name"] and d["ag_applied"] == fingerprint:
            continue
        if existing is None:
            existing = {c["name"]: c for c in ((await adguard.clients()).get("clients") or [])}
        current = existing.get(d["ag_client_name"]) if d["ag_client_name"] else None
        taken = {n for n in existing if n != d["ag_client_name"]}
        name = want_name if want_name not in taken else f"{want_name} #{d['id']}"
        if current:
            body = {**current, **payload, "name": name}
            await adguard.update_client(d["ag_client_name"], body)
            existing.pop(d["ag_client_name"], None)
        else:
            body = {**payload, "name": name, "upstreams": [], "tags": [],
                    "ignore_querylog": False, "ignore_statistics": False}
            await adguard.add_client(body)
        existing[name] = body
        db.ex("UPDATE devices SET ag_client_name=?, ag_applied=? WHERE id=?", (name, fingerprint, d["id"]))


_lock: asyncio.Lock | None = None


def reset_lock() -> None:
    """Called when the event loop (re)starts."""
    global _lock
    _lock = asyncio.Lock()


async def enforce_once() -> dict:
    if _lock is None:
        reset_lock()
    async with _lock:
        return await _enforce()


async def _enforce() -> dict:
    now = time.time()
    # Expired timed pauses.
    db.ex("UPDATE devices SET paused_until=NULL WHERE paused_until IS NOT NULL AND paused_until<=?", (now,))
    state = device_block_state(now)
    paused_ids = [did for did, st in state.items() if st["paused"]]
    try:
        limit_blocks = await asyncio.to_thread(limit_blocks_now)
        for did, doms in (await asyncio.to_thread(app_blocks_now)).items():
            limit_blocks.setdefault(did, set()).update(doms)
        ips = await _sync_pause_rules(paused_ids, limit_blocks)
        await _sync_clients(state)
        STATUS["enforcer"].update(last_run=now, error=None, blocked_ips=ips)
    except Exception as e:
        STATUS["enforcer"].update(last_run=now, error=str(e))
        raise
    return {"paused_devices": paused_ids}


async def forget_client(d: dict) -> None:
    if d.get("ag_client_name"):
        try:
            await adguard.delete_client(d["ag_client_name"])
        except adguard.AdGuardError:
            pass
