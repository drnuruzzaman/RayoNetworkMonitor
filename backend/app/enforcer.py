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


# ------------------------------------------------------------------ AdGuard sync
async def _sync_pause_rules(paused_ids: list[int]) -> list[str]:
    ips = sorted({ip for did in paused_ids for ip in device_ips(did)})
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
    if ips:
        new += ([""] if kept else []) + [BEGIN] + [f"||*^$client={ip},important" for ip in ips] + [END]
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
        ips = await _sync_pause_rules(paused_ids)
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
