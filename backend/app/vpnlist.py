"""VPN blocklist for AdGuard Home.

AdGuard's own Filters → Blocked services list is built into AdGuard and can't be extended, so HomeNet publishes
a normal DNS blocklist instead (every address of every app in the "VPN" category of Apps & categories) and
subscribes AdGuard to it under Filters → DNS blocklists, where it has its own on/off switch.
It blocks for the whole network; per-device blocking is done from a device's Controls tab instead.
"""
import hashlib
import time
from urllib.parse import urlparse

from . import adguard, db
from . import settings_store as S

CATEGORY = "VPN"
LIST_NAME = "HomeNet – VPN services"
PATH = "/api/blocklists/vpn.txt"


def domains() -> list[str]:
    """Every address of every (non-hidden) app in the VPN category."""
    out: set[str] = set()
    for r in db.q("SELECT domains FROM services WHERE lower(category)=lower(?) AND IFNULL(hidden,0)=0", (CATEGORY,)):
        out.update(d for d in db.jload(r["domains"], []) if d)
    return sorted(out)


def render() -> str:
    doms = domains()
    lines = [f"! Title: {LIST_NAME}",
             "! Description: Addresses of VPN and proxy apps from HomeNet's Apps & categories (category: VPN).",
             f"! Last modified: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
             f"! Entries: {len(doms)}", ""]
    lines += [f"||{d}^" for d in doms]
    return "\n".join(lines) + "\n"


def fingerprint() -> str:
    return hashlib.sha1("\n".join(domains()).encode()).hexdigest()


def list_url() -> str:
    """Where AdGuard Home can download the list from HomeNet."""
    ag_host = (urlparse(S.get("adguard_url") or "").hostname or "").lower()
    me = db.q1("SELECT ip FROM devices WHERE is_self=1 AND ip IS NOT NULL")
    my_ip = me["ip"] if me else None
    local = ag_host in ("", "localhost", "127.0.0.1", "::1") or (my_ip and ag_host == my_ip)
    if not local and S.get("ui_bind_host") == "127.0.0.1":
        raise adguard.AdGuardError("AdGuard Home runs on another machine, but HomeNet only accepts connections from "
                                   "this PC. Set 'Who can open the dashboard' to 'Whole home network' first.")
    host = "127.0.0.1" if local or not my_ip else my_ip
    return f"http://{host}:{S.get('ui_port')}{PATH}"


async def _find() -> dict | None:
    url = list_url()
    st = await adguard.filtering_status()
    return next((f for f in st.get("filters") or [] if f.get("url") == url), None)


async def status() -> dict:
    doms = domains()
    out = {"name": LIST_NAME, "category": CATEGORY, "entries": len(doms), "installed": False, "enabled": False,
           "rules_count": None, "last_updated": None, "error": None, "url": None}
    try:
        out["url"] = list_url()
        f = await _find()
    except adguard.AdGuardError as e:
        return {**out, "error": str(e)}
    if f:
        out.update(installed=True, enabled=bool(f.get("enabled")), rules_count=f.get("rules_count"),
                   last_updated=f.get("last_updated"))
    return out


async def refresh() -> None:
    """Ask AdGuard to re-download its blocklists now (it otherwise does so on its own schedule)."""
    await adguard.request("POST", "/filtering/refresh", json={"whitelist": False}, timeout=60)
    S.set("vpn_blocklist_fingerprint", fingerprint())


async def set_enabled(enabled: bool) -> dict:
    """Add the list to AdGuard's DNS blocklists if needed, and switch it on or off."""
    url = list_url()
    f = await _find()
    if not f:
        await adguard.request("POST", "/filtering/add_url", json={"name": LIST_NAME, "url": url, "whitelist": False}, timeout=60)
        if not enabled:
            await adguard.request("POST", "/filtering/set_url", json={
                "url": url, "whitelist": False, "data": {"name": LIST_NAME, "url": url, "enabled": False}})
    elif bool(f.get("enabled")) != enabled:
        await adguard.request("POST", "/filtering/set_url", json={
            "url": url, "whitelist": False, "data": {"name": f.get("name") or LIST_NAME, "url": url, "enabled": enabled}})
    if enabled:
        await refresh()
    return await status()


async def remove() -> dict:
    f = await _find()
    if f:
        await adguard.request("POST", "/filtering/remove_url", json={"url": f["url"], "whitelist": False})
    return await status()


async def sync_if_changed() -> bool:
    """Called periodically: if the VPN apps changed since AdGuard last downloaded the list, refresh it."""
    if S.get("vpn_blocklist_fingerprint") == fingerprint():
        return False
    try:
        f = await _find()
    except adguard.AdGuardError:
        return False
    if not f or not f.get("enabled"):
        return False
    await refresh()
    return True
