"""Password hashing, signed session tokens and Windows DPAPI secret protection."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${_b64(salt)}${_b64(h)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=_unb64(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, _unb64(h))
    except Exception:
        return False


# ---------------------------------------------------------------- tokens
def make_token(secret: str, ttl_hours: float) -> str:
    payload = _b64(json.dumps({"exp": time.time() + ttl_hours * 3600, "n": secrets.token_hex(8)}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def check_token(secret: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    expect = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        return False
    try:
        return json.loads(_unb64(payload))["exp"] > time.time()
    except Exception:
        return False


# ---------------------------------------------------------------- secrets at rest (DPAPI on Windows)
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _dpapi(data: bytes, protect: bool) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        inp = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = _Blob()
        fn = _crypt32.CryptProtectData if protect else _crypt32.CryptUnprotectData
        if protect:
            ok = fn(ctypes.byref(inp), "homenet", None, None, None, 0x1, ctypes.byref(out))
        else:
            ok = fn(ctypes.byref(inp), None, None, None, None, 0x1, ctypes.byref(out))
        if not ok:
            raise OSError("DPAPI call failed")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)


def protect(plain: str) -> str:
    if not plain:
        return ""
    if sys.platform == "win32":
        return "dpapi:" + _b64(_dpapi(plain.encode(), True))
    return "b64:" + _b64(plain.encode())


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    try:
        if stored.startswith("dpapi:") and sys.platform == "win32":
            return _dpapi(_unb64(stored[6:]), False).decode()
        if stored.startswith("b64:"):
            return _unb64(stored[4:]).decode()
    except Exception:
        return ""
    return stored
