import secrets
import time

from fastapi import HTTPException, Request

from . import settings_store as S
from .security import check_token, make_token

LEGACY_COOKIE = "homenet_session"
_failures: dict[str, list[float]] = {}


def cookie_name() -> str:
    # Browsers share cookies across ports on the same host, so include the port to keep
    # two HomeNet instances (e.g. a test copy) from signing each other out.
    return f"homenet_session_{S.get('ui_port')}"


def clear_cookies(response) -> None:
    for name in (cookie_name(), LEGACY_COOKIE):
        response.delete_cookie(name, path="/")


def token_secret() -> str:
    s = S.get("token_secret")
    if not s:
        s = secrets.token_hex(32)
        S.set("token_secret", s)
    # Changing the password invalidates every existing session.
    return s + (S.get("admin_password_hash") or "")


def issue(response) -> None:
    hours = S.get("session_hours")
    response.set_cookie(cookie_name(), make_token(token_secret(), hours), max_age=int(hours * 3600),
                        httponly=True, samesite="strict", path="/")


def is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def require_auth(request: Request) -> None:
    if not S.get("admin_password_hash"):
        raise HTTPException(status_code=401, detail="setup_required")
    secret = token_secret()
    if not any(check_token(secret, request.cookies.get(n)) for n in (cookie_name(), LEGACY_COOKIE)):
        raise HTTPException(status_code=401, detail="Please sign in")


def throttle(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < 300]
    _failures[ip] = recent
    if len(recent) >= 8:
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")


def record_failure(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    _failures.setdefault(ip, []).append(time.time())
