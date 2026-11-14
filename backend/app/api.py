import asyncio  # noqa: F401 (used by async endpoints)
import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import adguard, alerts, db, dhcp, diagnostics, enforcer, netinfo, oui, scanner, tasks, usage
from . import devices as D
from . import settings_store as S
from .auth import clear_cookies, is_local, issue, record_failure, require_auth, throttle
from .config import DB_PATH, VERSION
from .security import hash_password, verify_password
from .state import STATUS
from .timeutil import RANGES

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
    if any(k.startswith("dhcp_") for k in changed):
        tasks.kick("dhcp")
    if any(k.startswith("adguard") for k in changed):
        STATUS["adguard"].update(ok=None, error=None)
        tasks.kick("sync")
        tasks.kick("enforce")
    if any(k.startswith("scan") or k in ("probe_wait_sec", "max_scan_hosts") for k in changed):
        tasks.kick("scan")
    return {"settings": S.public_view(), "changed": changed, "restart_required": restart}


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
        "now": time.time(),
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
    online_out = []
    for d in sorted(online, key=lambda x: -(per_dev.get(x["id"], {}).get("seconds", 0))):
        s = D.serialize(d, now)
        s["paused"] = state[d["id"]]["paused"]
        s["today_seconds"] = per_dev.get(d["id"], {}).get("seconds", 0)
        s["top"] = per_dev.get(d["id"], {}).get("top", [])
        online_out.append(s)
    return {
        "counts": {
            "total": len(devs),
            "online": len(online),
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


# ====================================================================== devices
@api.get("/devices")
def list_devices():
    now = time.time()
    state = enforcer.device_block_state(now)
    per_dev = {d["device_id"]: d for d in usage.summary("today")["devices"]}
    out = []
    for d in db.q("SELECT * FROM devices ORDER BY is_online DESC, last_seen DESC"):
        s = D.serialize(d, now)
        st = state.get(d["id"], {})
        s["paused"] = st.get("paused", False)
        s["block_reasons"] = st.get("reasons", [])
        s["today_seconds"] = per_dev.get(d["id"], {}).get("seconds", 0)
        s["top"] = per_dev.get(d["id"], {}).get("top", [])
        out.append(s)
    return {"devices": out, "types": D.DEVICE_TYPES}


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
    s.update(recent_lookups=recent, adguard_enabled=S.get("adguard_enabled"))
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
            c[k] = [str(x) for x in body[k]] if k == "blocked_services" else bool(body[k])
    D.save_controls(device_id, c)
    tasks.kick("enforce")
    return get_device(device_id)


@api.get("/devices/{device_id}/presence")
def device_presence(device_id: int, range: str = "today"):
    _device_or_404(device_id)
    return {"sessions": usage.presence_timeline(device_id, _range(range))}


# ====================================================================== usage
@api.get("/usage/summary")
def usage_summary(range: str = "today", device_id: int | None = None, include_system: bool = False):
    return usage.summary(_range(range), device_id, include_system)


@api.get("/usage/sessions")
def usage_sessions(range: str = "today", device_id: int | None = None):
    return {"sessions": usage.recent_sessions(_range(range), device_id)}


@api.get("/usage/domains")
def usage_domains(range: str = "today", device_id: int | None = None, unmapped: bool = False, limit: int = 100):
    return {"domains": usage.top_domains(_range(range), device_id, unmapped, min(limit, 1000))}


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


def _services_changed():
    usage.invalidate_matcher()
    usage.rematch_recent()


@api.get("/services")
def list_services():
    rows = db.q("SELECT * FROM services ORDER BY category, name")
    cats = sorted({r["category"] for r in rows})
    return {"services": [{**r, "domains": db.jload(r["domains"], []), "track_time": bool(r["track_time"])} for r in rows],
            "categories": cats}


@api.post("/services")
def add_service(body: ServiceBody):
    if db.q1("SELECT id FROM services WHERE name=?", (body.name.strip(),)):
        raise HTTPException(409, "An app with that name already exists.")
    db.ex("INSERT INTO services(name, category, domains, track_time) VALUES(?,?,?,?)",
          (body.name.strip(), body.category.strip(), json.dumps(_clean_domains(body.domains)), int(body.track_time)))
    _services_changed()
    return list_services()


@api.put("/services/{sid}")
def update_service(sid: int, body: ServiceBody):
    if not db.q1("SELECT id FROM services WHERE id=?", (sid,)):
        raise HTTPException(404, "Not found")
    db.ex("UPDATE services SET name=?, category=?, domains=?, track_time=? WHERE id=?",
          (body.name.strip(), body.category.strip(), json.dumps(_clean_domains(body.domains)), int(body.track_time), sid))
    _services_changed()
    return list_services()


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
    _services_changed()
    return {"ok": True}


# ====================================================================== AdGuard passthrough
_svc_cache: dict = {"ts": 0, "data": []}


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
