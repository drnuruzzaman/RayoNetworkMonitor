"""Background loops. Each loop re-reads its settings every cycle, so UI changes apply live."""
import asyncio
import logging
import time

from . import adguard, alerts, detect, dhcp, enforcer, psl, scanner, usage
from . import settings_store as S
from .state import STATUS

log = logging.getLogger("homenet")
_wake: dict[str, asyncio.Event] = {}
_loop: asyncio.AbstractEventLoop | None = None


def kick(name: str) -> None:
    """Wake a loop early. Safe to call from request threads."""
    ev = _wake.get(name)
    if ev and _loop:
        _loop.call_soon_threadsafe(ev.set)


async def _sleep(name: str, seconds: float) -> None:
    try:
        await asyncio.wait_for(_wake[name].wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    _wake[name].clear()


async def scan_loop():
    await asyncio.sleep(2)
    while True:
        if S.get("scan_enabled") and S.get("setup_complete"):
            try:
                await scanner.scan_once()
            except Exception as e:
                log.warning("scan failed: %s", e)
        await _sleep("scan", S.get("scan_interval_sec"))


async def sync_loop():
    await asyncio.sleep(5)
    last_cleanup = 0.0
    while True:
        if S.get("adguard_enabled"):
            try:
                st = await adguard.status()
                was_ok = STATUS["adguard"]["ok"]
                STATUS["adguard"].update(ok=True, error=None, version=st.get("version"))
                await usage.sync_loop_once()
                STATUS["adguard"]["last_sync"] = time.time()
                try:
                    n = await usage.backfill_block_sources()
                    if n:
                        log.info("labelled %s earlier blocked lookups with their reason", n)
                except Exception as e:
                    log.warning("block-reason backfill failed: %s", e)
                await catalog_maintenance()
                if was_ok is False:
                    alerts.add("adguard_up", "AdGuard Home is reachable again", level="success")
            except Exception as e:
                was_ok = STATUS["adguard"]["ok"]
                STATUS["adguard"].update(ok=False, error=str(e))
                if was_ok is not False and S.get("alert_adguard_down"):
                    alerts.add("adguard_down", "Can't reach AdGuard Home", str(e), level="error")
        else:
            STATUS["adguard"].update(ok=None, error=None)
        if time.time() - last_cleanup > 3600:
            try:
                usage.cleanup()
            except Exception as e:
                log.warning("cleanup failed: %s", e)
            last_cleanup = time.time()
        await _sleep("sync", S.get("adguard_poll_sec"))


async def catalog_maintenance() -> None:
    """Keeps automatic app detection fed: domain-ending list, AdGuard's app list, one-off backfill."""
    try:
        if not psl.loaded():
            await asyncio.to_thread(psl.load_from_disk)
        if psl.needs_refresh():
            n = await psl.refresh()
            log.info("downloaded %s domain-ending rules", n)
    except Exception as e:
        log.warning("domain-ending list refresh failed (using built-in fallback): %s", e)
    if S.get("adguard_catalog_sync"):
        try:
            r = await detect.sync_adguard_catalog()
            if r.get("changed_ids"):
                usage.invalidate_matcher()
                usage.rematch_recent()
                for sid in r["changed_ids"]:
                    usage.rebuild_sessions(sid)
                log.info("AdGuard app list: %s added, %s updated", r["added"], r["updated"])
        except Exception as e:
            log.warning("AdGuard app list sync failed: %s", e)
    if S.get("auto_detect_apps") and not S.get("auto_detect_backfilled") and psl.loaded():
        try:
            n = await asyncio.to_thread(detect.backfill_unknown)
            new_ids = await asyncio.to_thread(detect.promote_ready)
            await asyncio.to_thread(usage.apply_new_apps, new_ids)
            S.set("auto_detect_backfilled", True)
            log.info("auto-detect backfill: scanned %s lookups, created %s apps", n, len(new_ids))
        except Exception as e:
            log.warning("auto-detect backfill failed: %s", e)


async def enforce_loop():
    await asyncio.sleep(4)
    while True:
        if S.get("adguard_enabled") and STATUS["adguard"]["ok"] is not False:
            try:
                await enforcer.enforce_once()
            except Exception as e:
                log.warning("enforce failed: %s", e)
        await _sleep("enforce", 30)


async def dhcp_loop():
    # Warm the slow PowerShell lookups so the Address server page opens quickly.
    for fn in (dhcp._resolve_iface, dhcp.firewall_status):
        try:
            await asyncio.to_thread(fn)
        except Exception:
            pass
    while True:
        try:
            await asyncio.to_thread(dhcp.SERVER.ensure)
        except Exception as e:
            log.warning("dhcp supervisor failed: %s", e)
        await _sleep("dhcp", 15)


def start() -> list[asyncio.Task]:
    global _loop
    _loop = asyncio.get_running_loop()
    for k in ("scan", "sync", "enforce", "dhcp"):
        _wake[k] = asyncio.Event()
    enforcer.reset_lock()
    usage.reset_lock()
    STATUS["started"] = time.time()
    return [asyncio.create_task(scan_loop()), asyncio.create_task(sync_loop()), asyncio.create_task(enforce_loop()),
            asyncio.create_task(dhcp_loop())]
