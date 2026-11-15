import asyncio  # noqa: F401 (used by async endpoints)
import json
import os
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import activity, adguard, alerts, db, detect, dhcp, diagnostics, enforcer, netinfo, oui, psl, scanner, tasks, usage, vpnlist
from . import devices as D
from . import settings_store as S
from .auth import clear_cookies, is_local, issue, record_failure, require_auth, throttle
from .config import DB_PATH, VERSION
from .security import hash_password, verify_password
from .state import STATUS
from .timeutil import RANGES, range_bounds

public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def _range(r: str) -> str:
    if r not in RANGES:
        raise HTTPException(400, f"range must be one of {sorted(RANGES)}")
    return r


# ====================================================================== auth & setup
class PasswordBody(BaseModel):
    password: str


@public.get("/setup/status")
def setup_status(request: Request):
    return {"password_set": bool(S.get("admin_password_hash")), "setup_complete": bool(S.get("setup_complete")),
            "is_local": is_local(request), "version": VERSION}


def _server_clock() -> dict:
    """The HomeNet server's clock (the PC on the network) so every viewer sees the same time, not their own."""
    local = datetime.now().astimezone()
    off = local.utcoffset()
    return {"now": time.time(), "tz_offset": int(off.total_seconds() // 60) if off else 0, "tz": local.tzname(),
            "display_tz": S.get("display_timezone") or None}


@public.get("/time")
def server_time():
    return _server_clock()


@public.post("/setup/password")
def setup_password(body: PasswordBody, request: Request, response: Response):
    if S.get("admin_password_hash"):
        raise HTTPException(409, "An admin password is already set. Sign in instead.")
    if not is_local(request):
        raise HTTPException(403, "For security, create the admin password on the PC running HomeNet (open http://localhost).")
    if len(body.password) < 8:
        raise HTTPException(400, "Use at least 8 characters.")
    S.set("admin_password_hash", hash_password(body.password))
    issue(response)
    return {"ok": True}


@public.post("/auth/login")
def login(body: PasswordBody, request: Request, response: Response):
    throttle(request)
    stored = S.get("admin_password_hash")
    if not stored:
        raise HTTPException(401, "setup_required")
    if not verify_password(body.password, stored):
        record_failure(request)
        raise HTTPException(401, "That password isn't right.")
    issue(response)
    return {"ok": True}


@public.post("/auth/logout")
def logout(response: Response):
    clear_cookies(response)
    return {"ok": True}


@api.get("/auth/me")
def me():
    return {"authenticated": True, "setup_complete": bool(S.get("setup_complete"))}


@api.post("/setup/complete")
def setup_complete():
    S.set("setup_complete", True)
    tasks.kick("scan")
    return {"ok": True}


class ChangePassword(BaseModel):
    current: str
    new: str


@api.post("/settings/password")
def change_password(body: ChangePassword, response: Response):
    if not verify_password(body.current, S.get("admin_password_hash")):
        raise HTTPException(400, "Your current password isn't right.")
    if len(body.new) < 8:
        raise HTTPException(400, "Use at least 8 characters.")
    S.set("admin_password_hash", hash_password(body.new))
    issue(response)
    return {"ok": True}


# ====================================================================== settings
@api.get("/settings")
def get_settings():
    return {"settings": S.public_view()}


@api.put("/settings")
def put_settings(body: dict):
    changed, restart, pending = [], False, {}
    for key, value in body.items():
        if not S.is_editable(key):
            raise HTTPException(400, f"Unknown setting: {key}")
        spec = next(s for s in S.SCHEMA if s["key"] == key)
        if spec.get("secret") and (value is None or value == ""):
            continue  # blank = keep existing secret
        try:
            pending[key] = S.coerce(key, value)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e) or f"Invalid value for {spec['label']}")
    # Validate DHCP settings as a whole before saving anything.
    if any(k.startswith("dhcp_") for k in pending):
        try:
            cfg = dhcp.build_config(pending)
        except dhcp.ConfigError as e:
            raise HTTPException(400, str(e))
        if pending.get("dhcp_enabled") and not cfg["static_ip"]:
            raise HTTPException(400, "This PC's IP address isn't static yet. Give it a fixed IP in Windows network settings first.")
    for key, v in pending.items():
        spec = next(s for s in S.SCHEMA if s["key"] == key)
        if v != S.get(key):
            S.set(key, v)
            changed.append(key)
            restart = restart or bool(spec.get("restart"))
    _settings_changed(changed)
    return {"settings": S.public_view(), "changed": changed, "restart_required": restart}


def _settings_changed(changed: list[str]) -> None:
    """Wake the loops that depend on the settings that just changed."""
    if any(k.startswith("dhcp_") for k in changed):
        tasks.kick("dhcp")
    if any(k.startswith("adguard") for k in changed):
        STATUS["adguard"].update(ok=None, error=None)
        tasks.kick("sync")
        tasks.kick("enforce")
    if any(k.startswith("scan") or k in ("probe_wait_sec", "max_scan_hosts") for k in changed):
        tasks.kick("scan")


def _defaults_view() -> dict:
    """Your saved defaults (if any) and which current settings differ from the defaults."""
    sd = S.saved_defaults()
    specs = {s["key"]: s for s in S.SCHEMA}
    apps = sd.get("apps")
    return {
        "saved": sd.get("saved"), "count": len(sd.get("settings") or {}), "file": S.DEFAULTS_FILE.name,
        "differs": [{"key": k, "label": specs[k]["label"], "group": specs[k]["group"], "current": S.get(k),
                     "default": S._default(k), "restart": bool(specs[k].get("restart"))} for k in S.differing_keys()],
        # Apps are only reset when your defaults include them (there is no "built-in" version of your app list).
        "apps": {"count": len(apps), "diff": usage.catalog_diff(apps)} if apps else None,
    }


@api.get("/settings/defaults")
def get_settings_defaults():
    return _defaults_view()


@api.post("/settings/defaults/save")
def save_settings_defaults():
    """Save the current settings and 'Apps & categories' list as your defaults."""
    S.save_defaults(apps=usage.catalog_snapshot())
    return _defaults_view()


@api.post("/settings/defaults/apply")
def apply_settings_defaults():
    """Set every setting back to the defaults (yours if saved, else built-in), and the app list to yours if saved."""
    specs = {s["key"]: s for s in S.SCHEMA}
    changed = S.reset_to_defaults()
    _settings_changed(changed)
    apps = S.saved_defaults().get("apps")
    app_diff = usage.apply_catalog(apps) if apps else None
    if app_diff and any(app_diff.values()):
        tasks.kick("enforce")  # app addresses feed blocking and time limits
    return {**_defaults_view(), "settings": S.public_view(), "changed": changed, "apps_changed": app_diff,
            "restart_required": any(specs[k].get("restart") for k in changed)}


@api.delete("/settings/defaults")
def clear_settings_defaults():
    """Forget your saved defaults; the built-in ones apply again (current settings are kept)."""
    S.clear_defaults()
    return _defaults_view()


@api.get("/settings/defaults/export")
def export_settings():
    """All current settings (passwords excluded) and the 'Apps & categories' list as a JSON document, for download."""
    return S.export_document(S.snapshot(), usage.catalog_snapshot())


@api.post("/settings/defaults/import")
def import_settings_defaults(body: dict):
    """Use an exported file as your defaults. Doesn't change current settings or apps until applied."""
    if body.get("app") != "HomeNet" or not isinstance(body.get("settings"), dict):
        raise HTTPException(400, "That isn't a HomeNet settings file.")
    values, skipped = S.validate_values(body["settings"])
    apps = S.validate_apps(body.get("apps"))
    if not values and not apps:
        raise HTTPException(400, "The file has no settings HomeNet can use.")
    S.save_defaults(values, apps)
    return {**_defaults_view(), "imported": len(values), "imported_apps": len(apps or []), "skipped": skipped}


class AdGuardTest(BaseModel):
    url: str | None = None
    username: str | None = None
    password: str | None = None


@api.post("/settings/adguard/test")
async def adguard_test(body: AdGuardTest):
    try:
        st = await adguard.status(cfg=body.model_dump())
        return {"ok": True, "version": st.get("version"), "running": st.get("running"),
                "protection_enabled": st.get("protection_enabled"), "dns_addresses": st.get("dns_addresses")}
    except adguard.AdGuardError as e:
        return {"ok": False, "error": str(e)}


# ====================================================================== system
@api.get("/system/status")
def system_status():
    size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    return {
        "version": VERSION,
        "status": STATUS,
        "oui_entries": oui.count(),
        "oui_updated": S.get("oui_updated"),
        "db_size": size,
        "devices": db.val("SELECT COUNT(*) FROM devices"),
        "queries": db.val("SELECT COUNT(*) FROM dns_queries"),
        "bind": {"host": S.get("ui_bind_host"), "port": S.get("ui_port")},
        "adguard_enabled": S.get("adguard_enabled"),
        **_server_clock(),
    }


@api.get("/system/interfaces")
async def interfaces():
    try:
        return {"interfaces": await asyncio.to_thread(netinfo.list_interfaces)}
    except Exception as e:
        raise HTTPException(500, f"Couldn't read network adapters: {e}")


@api.get("/system/diagnostics")
async def diagnostics_view(refresh: bool = False):
    return await diagnostics.run(force=refresh)


@api.post("/system/scan")
async def scan_now():
    try:
        return await scanner.scan_once()
    except Exception as e:
        raise HTTPException(500, str(e))


@api.post("/system/sync")
async def sync_now():
    if not S.get("adguard_enabled"):
        raise HTTPException(400, "AdGuard Home is turned off in Settings.")
    try:
        n = await usage.sync_loop_once()
        STATUS["adguard"].update(ok=True, error=None, last_sync=time.time())
        await enforcer.enforce_once()
        return {"ingested": n}
    except adguard.AdGuardError as e:
        STATUS["adguard"].update(ok=False, error=str(e))
        raise HTTPException(502, str(e))


@api.post("/system/oui-update")
async def oui_update():
    try:
        return {"entries": await oui.update_from_url()}
    except Exception as e:
        raise HTTPException(502, f"Couldn't download the manufacturer list: {e}")


@api.post("/system/restart")
def restart(request: Request):
    server = getattr(request.app.state, "server", None)
    if server is None:
        raise HTTPException(400, "Restart isn't available in this mode. Close and re-open HomeNet.")
    request.app.state.restart = True
    server.should_exit = True
    return {"ok": True, "host": S.get("ui_bind_host"), "port": S.get("ui_port")}


# ====================================================================== dashboard
@api.get("/dashboard")
def dashboard():
    now = time.time()
    devs = db.q("SELECT * FROM devices")
    state = enforcer.device_block_state(now)
    today = usage.summary("today")
    per_dev = {d["device_id"]: d for d in today["devices"]}
    online = [d for d in devs if d["is_online"]]
    using = activity.in_use_now(now)
    online_out = []
    for d in sorted(online, key=lambda x: (not using.get(x["id"]), -(per_dev.get(x["id"], {}).get("seconds", 0)))):
        s = D.serialize(d, now)
        s["in_use"] = _in_use(d, using)
        s["paused"] = state[d["id"]]["paused"]
        s["today_seconds"] = per_dev.get(d["id"], {}).get("seconds", 0)
        s["top"] = per_dev.get(d["id"], {}).get("top", [])
        online_out.append(s)
    return {
        "counts": {
            "total": len(devs),
            "online": len(online),
            "in_use": sum(1 for d in online if using.get(d["id"])),
            "new_24h": sum(1 for d in devs if d["first_seen"] and now - d["first_seen"] < 86400),
            "paused": sum(1 for st in state.values() if st["paused"]),
            "unnamed_online": sum(1 for d in online if not d["name"]),
        },
        "queries": usage.query_counts("today"),
        "usage": {k: today[k] for k in ("total_seconds", "services", "categories", "timeline")},
        "online": online_out,
        "alerts": db.q("SELECT * FROM alerts ORDER BY ts DESC LIMIT 6"),
        "unread_alerts": db.val("SELECT COUNT(*) FROM alerts WHERE read=0"),
        "adguard": {"enabled": S.get("adguard_enabled"), **STATUS["adguard"]},
        "scan": STATUS["scan"],
    }


# ====================================================================== live activity
@api.get("/live")
def live():
    """Right now: who is using which app, and since when. Idle and untracked devices listed separately."""
    now = time.time()
    cur = activity.current_activity(now)
    in_use, idle, unknown = [], [], []
    for d in db.q("SELECT * FROM devices WHERE is_online=1"):
        if d["is_gateway"] or d["type"] in activity.NON_HUMAN_TYPES:
            continue
        s = {k: v for k, v in D.serialize(d, now).items() if k in ("id", "display_name", "owner", "type", "ip", "paused")}
        if d["id"] in cur:
            in_use.append({**s, **cur[d["id"]]})
        elif _in_use(d, {}) is False:
            idle.append(s)
        else:
            unknown.append(s)
    in_use.sort(key=lambda x: x["in_use_since"])
    # Idle devices, and in-use ones where no known app showed up in the window: their last app.
    last = {did: v for did, v in activity.last_used(now).items() if not cur.get(did, {}).get("apps")}
    return {"now": now, "in_use": in_use, "idle": idle, "untracked": unknown, "last_used": last,
            "enabled": bool(S.get("activity_detection") and S.get("adguard_enabled"))}


# ====================================================================== devices
@api.get("/devices")
def list_devices():
    now = time.time()
    state = enforcer.device_block_state(now)
    per_dev = {d["device_id"]: d for d in usage.summary("today")["devices"]}
    using = activity.in_use_now(now)
    out = []
    for d in db.q("SELECT * FROM devices ORDER BY is_online DESC, last_seen DESC"):
        s = D.serialize(d, now)
        s["in_use"] = _in_use(d, using)
        st = state.get(d["id"], {})
        s["paused"] = st.get("paused", False)
        s["block_reasons"] = st.get("reasons", [])
        s["today_seconds"] = per_dev.get(d["id"], {}).get("seconds", 0)
        s["top"] = per_dev.get(d["id"], {}).get("top", [])
        out.append(s)
    return {"devices": out, "types": D.DEVICE_TYPES}


def _in_use(d: dict, using: dict) -> bool | None:
    """True = someone is using it now, False = connected but idle/locked, None = can't tell
    (offline, activity detection off, or the device doesn't use AdGuard so we can't see its activity)."""
    if not d["is_online"] or not S.get("activity_detection") or not S.get("adguard_enabled"):
        return None
    if d["is_gateway"] or d["type"] in activity.NON_HUMAN_TYPES:
        return None
    if not d["last_dns"] or time.time() - d["last_dns"] > 3600:
        return None
    return bool(using.get(d["id"]))


def _device_or_404(device_id: int) -> dict:
    d = D.get(device_id)
    if not d:
        raise HTTPException(404, "Device not found")
    return d


@api.get("/devices/{device_id}")
def get_device(device_id: int):
    d = _device_or_404(device_id)
    st = enforcer.device_block_state().get(device_id, {})
    s = D.serialize(d)
    recent = db.q1("SELECT COUNT(*) AS total, IFNULL(SUM(blocked),0) AS blocked FROM dns_queries "
                   "WHERE device_id=? AND ts>?", (device_id, time.time() - 900))
    live = activity.current_activity().get(device_id)
    s.update(recent_lookups=recent, adguard_enabled=S.get("adguard_enabled"), in_use=_in_use(d, activity.in_use_now()),
             live=live, last_used=None if live and live.get("apps") else activity.last_used().get(device_id),
             background_hosts=db.q("SELECT domain, share FROM device_background WHERE device_id=? ORDER BY share DESC",
                                   (device_id,)) if S.get("activity_learn_background") else [])
    s.update(paused=st.get("paused", False), block_reasons=st.get("reasons", []),
             effective_blocked_services=sorted(st.get("services", [])),
             ips=enforcer.device_ips(device_id),
             rules=[{**r, "device_ids": db.jload(r["device_ids"], []), "days": db.jload(r["days"], []),
                     "services": db.jload(r["services"], []), "active": enforcer.rule_active(r)}
                    for r in db.q("SELECT * FROM rules") if device_id in db.jload(r["device_ids"], [])])
    return s


class DevicePatch(BaseModel):
    name: str | None = None
    owner: str | None = None
    type: str | None = None
    notes: str | None = None
    trusted: bool | None = None


@api.patch("/devices/{device_id}")
def patch_device(device_id: int, body: DevicePatch):
    _device_or_404(device_id)
    data = body.model_dump(exclude_unset=True)
    if "type" in data:
        if data["type"] not in D.DEVICE_TYPES:
            raise HTTPException(400, "Unknown device type")
        db.ex("UPDATE devices SET type=?, type_locked=1 WHERE id=?", (data.pop("type"), device_id))
    for k, v in data.items():
        if isinstance(v, str):
            v = v.strip() or None
        db.ex(f"UPDATE devices SET {k}=? WHERE id=?", (int(v) if isinstance(v, bool) else v, device_id))
    tasks.kick("enforce")
    return get_device(device_id)


@api.delete("/devices/{device_id}")
async def delete_device(device_id: int):
    d = _device_or_404(device_id)
    if S.get("adguard_enabled"):
        await enforcer.forget_client(d)
    db.ex("DELETE FROM devices WHERE id=?", (device_id,))
    tasks.kick("enforce")
    return {"ok": True}


class PauseBody(BaseModel):
    minutes: int | None = None  # None = until resumed


@api.post("/devices/{device_id}/pause")
def pause_device(device_id: int, body: PauseBody):
    d = _device_or_404(device_id)
    if d["is_self"]:
        raise HTTPException(400, "You can't pause the PC that runs HomeNet. It would block itself.")
    if body.minutes:
        db.ex("UPDATE devices SET paused=0, paused_until=? WHERE id=?", (time.time() + body.minutes * 60, device_id))
    else:
        db.ex("UPDATE devices SET paused=1, paused_until=NULL WHERE id=?", (device_id,))
    alerts.add("paused", f"Internet paused for {D.display_name(d)}",
               f"For {body.minutes} minutes" if body.minutes else "Until resumed", device_id=device_id)
    tasks.kick("enforce")
    return {"ok": True, "adguard_enabled": S.get("adguard_enabled")}


@api.post("/devices/{device_id}/resume")
def resume_device(device_id: int):
    d = _device_or_404(device_id)
    db.ex("UPDATE devices SET paused=0, paused_until=NULL WHERE id=?", (device_id,))
    alerts.add("resumed", f"Internet resumed for {D.display_name(d)}", device_id=device_id, level="success")
    tasks.kick("enforce")
    return {"ok": True}


@api.put("/devices/{device_id}/controls")
def put_controls(device_id: int, body: dict):
    _device_or_404(device_id)
    c = dict(D.DEFAULT_CONTROLS)
    for k in c:
        if k in body:
            if k == "blocked_services":
                c[k] = [str(x) for x in body[k]]
            elif k == "blocked_apps":
                known = {r["id"] for r in db.q("SELECT id FROM services")}
                c[k] = sorted({int(x) for x in body[k] if str(x).isdigit() and int(x) in known})
            else:
                c[k] = bool(body[k])
    D.save_controls(device_id, c)
    tasks.kick("enforce")
    return get_device(device_id)


@api.get("/devices/{device_id}/presence")
def device_presence(device_id: int, range: str = "today"):
    _device_or_404(device_id)
    r = _range(range)
    lo, hi, _ = range_bounds(r)
    in_use = activity.active_intervals(lo, hi, device_id).get(device_id, []) if S.get("activity_detection") else []
    return {"sessions": usage.presence_timeline(device_id, r),
            "in_use": [{"start": s, "end": e} for s, e in in_use],
            "in_use_seconds": round(activity.total(in_use))}


# ====================================================================== usage
@api.get("/usage/summary")
def usage_summary(range: str = "today", device_id: int | None = None, include_system: bool = False):
    return usage.summary(_range(range), device_id, include_system)


@api.get("/usage/screentime")
def usage_screentime(device_id: int | None = None, period: str = "week", date: str | None = None,
                     service_id: int | None = None):
    if period not in ("week", "day"):
        raise HTTPException(400, "period must be week or day")
    try:
        return usage.screentime(device_id, period, date, service_id)
    except ValueError:
        raise HTTPException(400, "date must look like 2026-11-14")


@api.get("/usage/sessions")
def usage_sessions(range: str = "today", device_id: int | None = None):
    return {"sessions": usage.recent_sessions(_range(range), device_id)}


@api.get("/usage/domains")
def usage_domains(range: str = "today", device_id: int | None = None, unmapped: bool = False, limit: int = 100,
                  in_use: bool = False, sort: str = "lookups"):
    return {"domains": usage.top_domains(_range(range), device_id, unmapped, min(limit, 1000), in_use_only=in_use,
                                         recent_first=(sort == "recent"))}


# ====================================================================== services catalog
class ServiceBody(BaseModel):
    name: str
    category: str
    domains: list[str]
    track_time: bool = True


def _clean_domains(domains: list[str]) -> list[str]:
    out = []
    for d in domains:
        d = d.strip().lower().replace("https://", "").replace("http://", "").split("/")[0].lstrip("*.").rstrip(".")
        if d and d not in out:
            out.append(d)
    return out


def _services_changed(sid: int | None = None):
    usage.invalidate_matcher()
    usage.rematch_recent()
    if sid:
        usage.rebuild_sessions(sid)  # so the change also applies to earlier activity, not just new lookups


@api.get("/services/learned-background")
def learned_background():
    """Per-device background chatter learned from the last 7 days (see activity.learn_background)."""
    if not S.get("activity_learn_background"):
        return {"enabled": False, "devices": [], "learned": None}
    rows = db.q("SELECT b.device_id, b.domain, b.share, b.learned, COALESCE(d.name, d.hostname, d.mac) AS device "
                "FROM device_background b JOIN devices d ON d.id=b.device_id ORDER BY device, b.share DESC")
    devices: dict[int, dict] = {}
    for r in rows:
        devices.setdefault(r["device_id"], {"id": r["device_id"], "name": r["device"], "hosts": []})["hosts"].append(
            {"domain": r["domain"], "share": r["share"]})
    return {"enabled": True, "devices": list(devices.values()), "learned": max((r["learned"] for r in rows), default=None)}


@api.get("/services")
def list_services():
    rows = db.q("SELECT * FROM services ORDER BY category, name")
    cats = sorted({r["category"] for r in rows})
    since = time.time() - 7 * 86400
    stats = {r["service_id"]: r for r in db.q(
        "SELECT service_id, COUNT(*) AS lookups, COUNT(DISTINCT device_id) AS devices, MAX(ts) AS last_seen "
        "FROM dns_queries WHERE ts>? AND service_id IS NOT NULL GROUP BY service_id", (since,))}
    out = []
    for r in rows:
        st = stats.get(r["id"], {})
        out.append({**r, "domains": db.jload(r["domains"], []), "track_time": bool(r["track_time"]),
                    "reviewed": bool(r["reviewed"]), "hidden": bool(r["hidden"]), "source": r["source"] or "builtin",
                    "lookups_7d": st.get("lookups", 0), "devices_7d": st.get("devices", 0), "last_seen": st.get("last_seen")})
    return {"services": out, "categories": cats,
            "review_count": sum(1 for s in out if s["source"] == "auto" and not s["reviewed"] and not s["hidden"]),
            "adguard_synced": S.get("adguard_catalog_synced"), "psl_loaded": psl.loaded(),
            "auto_detect": S.get("auto_detect_apps"),
            "pending_sites": db.val("SELECT COUNT(*) FROM unknown_sites") or 0}


class ReviewBody(BaseModel):
    name: str | None = None
    category: str | None = None
    background: bool | None = None


@api.post("/services/{sid}/review")
def review_service(sid: int, body: ReviewBody):
    row = db.q1("SELECT * FROM services WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "Not found")
    name = (body.name or row["name"]).strip()
    if name != row["name"] and db.q1("SELECT 1 FROM services WHERE lower(name)=lower(?) AND id!=?", (name, sid)):
        raise HTTPException(409, "Another app already has that name. Use Merge instead.")
    hidden = row["hidden"] if body.background is None else int(body.background)
    track = 0 if hidden else (row["track_time"] if body.background is None else 1)
    db.ex("UPDATE services SET name=?, category=?, hidden=?, track_time=?, reviewed=1 WHERE id=?",
          (name, (body.category or row["category"]).strip(), hidden, track, sid))
    return {"ok": True}


@api.post("/services/review-all")
def review_all():
    db.ex("UPDATE services SET reviewed=1 WHERE source='auto' AND reviewed=0")
    return {"ok": True}


class MergeBody(BaseModel):
    into: int


@api.post("/services/{sid}/merge")
def merge_service(sid: int, body: MergeBody):
    try:
        detect.merge(sid, body.into)
    except ValueError as e:
        raise HTTPException(400, str(e))
    usage.invalidate_matcher()
    usage.rebuild_sessions(body.into)
    return {"ok": True}


@api.post("/services/sync-adguard")
async def sync_adguard_apps():
    if not S.get("adguard_enabled"):
        raise HTTPException(400, "AdGuard Home isn't connected.")
    try:
        r = await detect.sync_adguard_catalog(force=True)
    except adguard.AdGuardError as e:
        raise HTTPException(502, str(e))
    if r.get("changed_ids"):
        await asyncio.to_thread(_after_sync, r["changed_ids"])
    return {"added": r.get("added", 0), "updated": r.get("updated", 0)}


def _after_sync(ids):
    usage.invalidate_matcher()
    usage.rematch_recent()
    for sid in ids:
        usage.rebuild_sessions(sid)


_SOURCE_RANK = {"auto": 0, "adguard": 1}  # matcher priority: higher rank wins, then the newer app (higher id)


def _domain_conflicts(domains: list[str], sid: int | None) -> list[dict]:
    """Addresses in `domains` that another app also lists exactly, and which app ends up getting them.
    sid=None means a new app (it will be 'yours', the newest)."""
    me = db.q1("SELECT id, name, source FROM services WHERE id=?", (sid,)) if sid else None
    my_key = (_SOURCE_RANK.get(me["source"], 2), me["id"]) if me else (2, float("inf"))
    wanted = set(_clean_domains(domains))
    out = []
    for s in db.q("SELECT id, name, source, domains FROM services" + (" WHERE id!=?" if sid else ""), (sid,) if sid else ()):
        for d in db.jload(s["domains"], []):
            if d in wanted:
                theirs = (_SOURCE_RANK.get(s["source"], 2), s["id"])
                out.append({"domain": d, "app": s["name"], "app_id": s["id"], "wins": "other" if theirs > my_key else "this"})
    return sorted(out, key=lambda c: (c["domain"], c["app"]))


class DomainCheckBody(BaseModel):
    domains: list[str]
    id: int | None = None


@api.post("/services/check-domains")
def check_domains(body: DomainCheckBody):
    """Live warning for the app editor: addresses another app already lists."""
    return {"conflicts": _domain_conflicts(body.domains, body.id)}


@api.post("/services")
def add_service(body: ServiceBody):
    if db.q1("SELECT id FROM services WHERE name=?", (body.name.strip(),)):
        raise HTTPException(409, "An app with that name already exists.")
    cur = db.ex("INSERT INTO services(name, category, domains, track_time, source, reviewed, created) VALUES(?,?,?,?,'user',1,?)",
                (body.name.strip(), body.category.strip(), json.dumps(_clean_domains(body.domains)), int(body.track_time), time.time()))
    _services_changed(cur.lastrowid)
    return {**list_services(), "conflicts": _domain_conflicts(body.domains, cur.lastrowid)}


@api.put("/services/{sid}")
def update_service(sid: int, body: ServiceBody):
    if not db.q1("SELECT id FROM services WHERE id=?", (sid,)):
        raise HTTPException(404, "Not found")
    # Editing an auto-detected app makes it yours (and marks it reviewed).
    db.ex("UPDATE services SET name=?, category=?, domains=?, track_time=?, hidden=CASE WHEN ?=1 THEN 0 ELSE hidden END, "
          "reviewed=1, source=CASE WHEN source='auto' THEN 'user' ELSE source END WHERE id=?",
          (body.name.strip(), body.category.strip(), json.dumps(_clean_domains(body.domains)), int(body.track_time),
           int(body.track_time), sid))
    _services_changed(sid)
    return {**list_services(), "conflicts": _domain_conflicts(body.domains, sid)}


@api.delete("/services/{sid}")
def delete_service(sid: int):
    db.ex("DELETE FROM services WHERE id=?", (sid,))
    _services_changed()
    return list_services()


class DomainBody(BaseModel):
    domain: str


@api.post("/services/{sid}/domains")
def add_domain(sid: int, body: DomainBody):
    row = db.q1("SELECT * FROM services WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "Not found")
    domains = _clean_domains(db.jload(row["domains"], []) + [body.domain])
    db.ex("UPDATE services SET domains=? WHERE id=?", (json.dumps(domains), sid))
    _services_changed(sid)
    return {"ok": True}


# ====================================================================== AdGuard passthrough
_svc_cache: dict = {"ts": 0, "data": []}


@public.get("/blocklists/vpn.txt")
def vpn_blocklist_file():
    """The VPN blocklist AdGuard Home downloads (no login: AdGuard fetches it). Only VPN app addresses, nothing private."""
    return Response(vpnlist.render(), media_type="text/plain; charset=utf-8")


class VpnListBody(BaseModel):
    enabled: bool


@api.get("/adguard/vpn-blocklist")
async def get_vpn_blocklist():
    return await vpnlist.status()


@api.put("/adguard/vpn-blocklist")
async def put_vpn_blocklist(body: VpnListBody):
    """Add HomeNet's VPN list to AdGuard's Filters → DNS blocklists and switch it on/off (whole network)."""
    try:
        return await vpnlist.set_enabled(body.enabled)
    except adguard.AdGuardError as e:
        raise HTTPException(502, str(e))


@api.post("/adguard/vpn-blocklist/refresh")
async def refresh_vpn_blocklist():
    try:
        await vpnlist.refresh()
        return await vpnlist.status()
    except adguard.AdGuardError as e:
        raise HTTPException(502, str(e))


@api.delete("/adguard/vpn-blocklist")
async def delete_vpn_blocklist():
    try:
        return await vpnlist.remove()
    except adguard.AdGuardError as e:
        raise HTTPException(502, str(e))


@api.get("/adguard/services")
async def adguard_services():
    if not S.get("adguard_enabled"):
        return {"services": [], "error": "AdGuard Home is turned off. Turn it on in Settings to block apps."}
    if time.time() - _svc_cache["ts"] > 3600 or not _svc_cache["data"]:
        try:
            data = await adguard.blocked_services_catalog()
            _svc_cache.update(ts=time.time(), data=[{"id": s.get("id"), "name": s.get("name"),
                                                      "icon_svg": s.get("icon_svg"), "group": s.get("group_id")}
                                                     for s in data])
        except adguard.AdGuardError as e:
            return {"services": [], "error": str(e)}
    return {"services": _svc_cache["data"]}


# ====================================================================== schedules
class RuleBody(BaseModel):
    name: str
    device_ids: list[int]
    action: str  # pause_internet | block_services
    services: list[str] = []
    days: list[int]
    start: str
    end: str
    enabled: bool = True


def _validate_rule(b: RuleBody):
    if b.action not in ("pause_internet", "block_services"):
        raise HTTPException(400, "Unknown action")
    if not b.device_ids:
        raise HTTPException(400, "Choose at least one device.")
    if not b.days or any(d not in range(7) for d in b.days):
        raise HTTPException(400, "Choose at least one day.")
    if b.action == "block_services" and not b.services:
        raise HTTPException(400, "Choose at least one app to block.")
    for t in (b.start, b.end):
        try:
            h, m = t.split(":")
            assert 0 <= int(h) < 24 and 0 <= int(m) < 60
        except Exception:
            raise HTTPException(400, "Times must look like 21:00.")


def _rule_out(r: dict) -> dict:
    return {**r, "device_ids": db.jload(r["device_ids"], []), "days": db.jload(r["days"], []),
            "services": db.jload(r["services"], []), "enabled": bool(r["enabled"]), "active": enforcer.rule_active(r)}


@api.get("/rules")
def list_rules():
    return {"rules": [_rule_out(r) for r in db.q("SELECT * FROM rules ORDER BY name")],
            "adguard_enabled": S.get("adguard_enabled")}


@api.post("/rules")
def add_rule(body: RuleBody):
    _validate_rule(body)
    db.ex("INSERT INTO rules(name, device_ids, action, services, days, start, end, enabled, created) "
          "VALUES(?,?,?,?,?,?,?,?,?)",
          (body.name.strip() or "Schedule", json.dumps(body.device_ids), body.action, json.dumps(body.services),
           json.dumps(sorted(set(body.days))), body.start, body.end, int(body.enabled), time.time()))
    tasks.kick("enforce")
    return list_rules()


@api.put("/rules/{rid}")
def update_rule(rid: int, body: RuleBody):
    _validate_rule(body)
    db.ex("UPDATE rules SET name=?, device_ids=?, action=?, services=?, days=?, start=?, end=?, enabled=? WHERE id=?",
          (body.name.strip() or "Schedule", json.dumps(body.device_ids), body.action, json.dumps(body.services),
           json.dumps(sorted(set(body.days))), body.start, body.end, int(body.enabled), rid))
    tasks.kick("enforce")
    return list_rules()


@api.delete("/rules/{rid}")
def delete_rule(rid: int):
    db.ex("DELETE FROM rules WHERE id=?", (rid,))
    tasks.kick("enforce")
    return list_rules()


# ====================================================================== daily time limits
class LimitBody(BaseModel):
    device_ids: list[int]
    target_type: str          # app | category
    target: str               # service id or category name
    minutes: int
    days: list[int] = [0, 1, 2, 3, 4, 5, 6]
    enabled: bool = True


def _validate_limit(b: LimitBody):
    if b.target_type not in ("app", "category"):
        raise HTTPException(400, "Choose an app or a category")
    if not b.device_ids:
        raise HTTPException(400, "Choose at least one device.")
    if not 1 <= b.minutes <= 24 * 60:
        raise HTTPException(400, "The limit must be between 1 minute and 24 hours.")
    if not b.days or any(d not in range(7) for d in b.days):
        raise HTTPException(400, "Choose at least one day.")
    if b.target_type == "app" and not db.q1("SELECT 1 FROM services WHERE id=?", (int(b.target),)):
        raise HTTPException(400, "That app no longer exists.")


@api.get("/limits")
def list_limits(device_id: int | None = None):
    return {"limits": enforcer.limits_usage(device_id), "adguard_enabled": S.get("adguard_enabled")}


@api.post("/limits")
def add_limit(body: LimitBody):
    _validate_limit(body)
    db.ex("INSERT INTO app_limits(device_ids, target_type, target, minutes, days, enabled, created) VALUES(?,?,?,?,?,?,?)",
          (json.dumps(body.device_ids), body.target_type, body.target, body.minutes, json.dumps(sorted(set(body.days))),
           int(body.enabled), time.time()))
    tasks.kick("enforce")
    return {"ok": True}


@api.put("/limits/{lid}")
def update_limit(lid: int, body: LimitBody):
    _validate_limit(body)
    db.ex("UPDATE app_limits SET device_ids=?, target_type=?, target=?, minutes=?, days=?, enabled=? WHERE id=?",
          (json.dumps(body.device_ids), body.target_type, body.target, body.minutes, json.dumps(sorted(set(body.days))),
           int(body.enabled), lid))
    tasks.kick("enforce")
    return {"ok": True}


@api.delete("/limits/{lid}")
def delete_limit(lid: int):
    db.ex("DELETE FROM app_limits WHERE id=?", (lid,))
    tasks.kick("enforce")
    return {"ok": True}


# ====================================================================== AdGuard global filter defaults
_gf_cache: dict = {"ts": 0, "data": None}


@api.get("/adguard/global-filters")
async def adguard_global_filters():
    """AdGuard's own (global) filter switches, used as each device's defaults."""
    if not S.get("adguard_enabled"):
        return {"available": False}
    if _gf_cache["data"] and time.time() - _gf_cache["ts"] < 60:
        return _gf_cache["data"]
    try:
        f, sb, pc, ss = await asyncio.gather(
            adguard.request("GET", "/filtering/status"), adguard.request("GET", "/safebrowsing/status"),
            adguard.request("GET", "/parental/status"), adguard.request("GET", "/safesearch/status"))
    except adguard.AdGuardError as e:
        return {"available": False, "error": str(e)}
    data = {"available": True, "filtering": bool(f.get("enabled")), "safebrowsing": bool(sb.get("enabled")),
            "parental": bool(pc.get("enabled")), "safe_search": bool(ss.get("enabled"))}
    _gf_cache.update(ts=time.time(), data=data)
    return data


# ====================================================================== alerts
@api.get("/alerts")
def list_alerts(limit: int = 200):
    rows = db.q("SELECT a.*, d.name AS device_name FROM alerts a LEFT JOIN devices d ON d.id=a.device_id "
                "ORDER BY a.ts DESC LIMIT ?", (min(limit, 1000),))
    return {"alerts": rows, "unread": db.val("SELECT COUNT(*) FROM alerts WHERE read=0")}


@api.post("/alerts/read-all")
def read_all():
    db.ex("UPDATE alerts SET read=1 WHERE read=0")
    return {"ok": True}


@api.delete("/alerts")
def clear_alerts():
    db.ex("DELETE FROM alerts")
    return {"ok": True}


# ====================================================================== DHCP address server
@api.get("/dhcp")
async def dhcp_view():
    cfg_res, firewall = await asyncio.gather(asyncio.to_thread(dhcp.build_config),
                                             asyncio.to_thread(dhcp.firewall_status), return_exceptions=True)
    if isinstance(cfg_res, Exception):
        cfg, cfg_error = None, str(cfg_res)
    else:
        cfg, cfg_error = cfg_res, None
    if isinstance(firewall, Exception):
        firewall = {"ok": None, "error": str(firewall)}
    st = dhcp.SERVER.status
    return {
        "settings": [s for s in S.public_view() if s["group"] == "dhcp"],
        "enabled": S.get("dhcp_enabled"),
        "config": cfg,
        "config_error": cfg_error,
        "status": {k: st[k] for k in ("running", "error", "started", "last_packet", "stats")},
        "other_servers": dhcp.SERVER.other_servers(),
        "events": list(dhcp.SERVER.events)[:50],
        "firewall": firewall,
        "leases": dhcp.leases(),
    }


@api.post("/dhcp/probe")
async def dhcp_probe():
    try:
        return await asyncio.to_thread(dhcp.probe)
    except Exception as e:
        raise HTTPException(500, f"Check failed: {e}")


class ReserveBody(BaseModel):
    ip: str | None = None


@api.post("/dhcp/leases/{mac}/reserve")
def dhcp_reserve(mac: str, body: ReserveBody):
    mac = netinfo.norm_mac(mac)
    if not mac:
        raise HTTPException(400, "Invalid MAC address")
    row = db.q1("SELECT * FROM dhcp_leases WHERE mac=?", (mac,))
    dev = db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
    ip = (body.ip or (row and row["ip"]) or (dev and dev["ip"]) or "").strip()
    try:
        cfg = dhcp.build_config()
    except dhcp.ConfigError as e:
        raise HTTPException(400, str(e))
    logic = dhcp.LeaseLogic(cfg)
    if not ip or not logic.in_subnet(ip):
        raise HTTPException(400, f"Enter an address inside {cfg['network']}.")
    if logic.taken_by_other(ip, mac, time.time()):
        raise HTTPException(400, f"{ip} is already used by another device.")
    db.ex("""INSERT INTO dhcp_leases(mac, ip, hostname, expires, static, updated) VALUES(?,?,?,NULL,1,?)
             ON CONFLICT(mac) DO UPDATE SET ip=excluded.ip, static=1, updated=excluded.updated""",
          (mac, ip, dev["hostname"] if dev else None, time.time()))
    return {"ok": True, "leases": dhcp.leases()}


@api.delete("/dhcp/leases/{mac}/reserve")
def dhcp_unreserve(mac: str):
    db.ex("UPDATE dhcp_leases SET static=0, expires=IFNULL(expires, ?) WHERE mac=?", (time.time(), netinfo.norm_mac(mac)))
    return {"ok": True, "leases": dhcp.leases()}


@api.delete("/dhcp/leases/{mac}")
def dhcp_forget(mac: str):
    db.ex("DELETE FROM dhcp_leases WHERE mac=? AND static=0", (netinfo.norm_mac(mac),))
    return {"ok": True, "leases": dhcp.leases()}
