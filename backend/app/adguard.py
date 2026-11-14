"""Thin async client for the AdGuard Home REST API (/control/*)."""
import httpx

from . import settings_store as S


class AdGuardError(Exception):
    pass


def _cfg(override: dict | None = None) -> dict:
    cfg = {"url": S.get("adguard_url"), "username": S.get("adguard_username"), "password": S.get("adguard_password")}
    if override:
        cfg.update({k: v for k, v in override.items() if v not in (None, "")})
    cfg["url"] = (cfg["url"] or "").rstrip("/")
    return cfg


async def request(method: str, path: str, *, json=None, params=None, cfg: dict | None = None, timeout: float = 15):
    c = _cfg(cfg)
    if not c["url"]:
        raise AdGuardError("AdGuard Home address isn't set. Add it in Settings → AdGuard Home.")
    auth = (c["username"], c["password"]) if c["username"] else None
    try:
        async with httpx.AsyncClient(base_url=c["url"], auth=auth, timeout=timeout) as client:
            r = await client.request(method, f"/control{path}", json=json, params=params)
    except httpx.ConnectError:
        raise AdGuardError(f"Can't connect to AdGuard Home at {c['url']}. Is it installed and running?")
    except httpx.TimeoutException:
        raise AdGuardError(f"AdGuard Home at {c['url']} didn't respond in time.")
    except httpx.HTTPError as e:
        raise AdGuardError(f"AdGuard Home request failed: {e}")
    if r.status_code in (401, 403):
        raise AdGuardError("AdGuard Home rejected the username or password.")
    if r.status_code == 302 or "text/html" in r.headers.get("content-type", ""):
        raise AdGuardError("AdGuard Home isn't set up yet. Finish its first-run setup, then try again.")
    if r.status_code >= 400:
        raise AdGuardError(f"AdGuard Home error {r.status_code}: {r.text.strip()[:300]}")
    if "application/json" in r.headers.get("content-type", ""):
        return r.json()
    return r.text


async def status(cfg: dict | None = None) -> dict:
    return await request("GET", "/status", cfg=cfg)


async def clients() -> dict:
    return await request("GET", "/clients")


async def add_client(client: dict):
    return await request("POST", "/clients/add", json=client)


async def update_client(name: str, client: dict):
    return await request("POST", "/clients/update", json={"name": name, "data": client})


async def delete_client(name: str):
    return await request("POST", "/clients/delete", json={"name": name})


async def blocked_services_catalog() -> list[dict]:
    try:
        data = await request("GET", "/blocked_services/all")
        return data.get("blocked_services", []) if isinstance(data, dict) else []
    except AdGuardError:
        data = await request("GET", "/blocked_services/services")
        return data if isinstance(data, list) else []


async def access_list() -> dict:
    return await request("GET", "/access/list")


async def access_set(data: dict):
    return await request("POST", "/access/set", json=data)


async def filtering_status() -> dict:
    return await request("GET", "/filtering/status")


async def set_user_rules(rules: list[str]):
    return await request("POST", "/filtering/set_rules", json={"rules": rules})


async def querylog(limit: int, older_than: str | None = None) -> dict:
    params = {"limit": limit}
    if older_than:
        params["older_than"] = older_than
    return await request("GET", "/querylog", params=params, timeout=30)
