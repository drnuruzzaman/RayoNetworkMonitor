"""Device helpers shared by the scanner, API and enforcement."""
import json
import time

from . import db

DEVICE_TYPES = ["phone", "tablet", "laptop", "computer", "tv", "console", "speaker",
                "camera", "iot", "router", "printer", "unknown"]

DEFAULT_CONTROLS = {
    "use_global": True,         # follow AdGuard's global filtering settings
    "filtering": True,
    "safe_search": False,
    "parental": False,
    "safebrowsing": True,
    "blocked_services": [],     # AdGuard service ids always blocked for this device
    "blocked_apps": [],         # HomeNet app ids (Apps & categories) always blocked, via AdGuard custom rules
}


def guess_type(hostname: str | None, vendor: str | None) -> str:
    h = (hostname or "").lower()
    v = (vendor or "").lower()
    if "iphone" in h:
        return "phone"
    if "ipad" in h:
        return "tablet"
    if any(x in h for x in ("macbook", "laptop-")):
        return "laptop"
    if any(x in h for x in ("imac", "mac-mini", "macmini", "desktop-")):
        return "computer"
    if any(x in h for x in ("android", "galaxy", "pixel", "sm-", "oneplus", "redmi", "oppo")):
        return "phone"
    if any(x in h for x in ("tab", "kindle", "fire")):
        return "tablet"
    if any(x in h for x in ("tv", "chromecast", "roku", "appletv", "apple-tv", "bravia", "tizen")):
        return "tv"
    if any(x in h for x in ("xbox", "playstation", "ps4", "ps5", "switch", "nintendo")):
        return "console"
    if any(x in h for x in ("echo", "sonos", "homepod", "google-home", "nest")):
        return "speaker"
    if "printer" in h or any(h.startswith(x) for x in ("hp", "epson", "brother", "canon")):
        return "printer"
    if any(x in h for x in ("familyhub", "fridge", "washer", "dryer", "vacuum", "roomba")):
        return "iot"
    if any(x in v for x in ("sonos", "amazon technologies")):
        return "speaker"
    if any(x in v for x in ("nintendo", "sony interactive", "microsoft")) and "xbox" in h:
        return "console"
    if any(x in v for x in ("espressif", "tuya", "shenzhen", "hikvision", "ring")):
        return "iot"
    return "unknown"


def display_name(d: dict) -> str:
    if d.get("name"):
        return d["name"]
    if d.get("hostname"):
        return d["hostname"].split(".")[0]
    if d.get("is_gateway"):
        return "Router"
    if d.get("vendor"):
        return f"{d['vendor'].split(',')[0]} device"
    return d.get("mac") or "Unknown device"


def controls(d: dict) -> dict:
    c = dict(DEFAULT_CONTROLS)
    c.update(db.jload(d.get("controls"), {}) or {})
    return c


def is_paused(d: dict, now: float | None = None) -> bool:
    now = now or time.time()
    return bool(d.get("paused")) or bool(d.get("paused_until") and d["paused_until"] > now)


def serialize(d: dict, now: float | None = None) -> dict:
    now = now or time.time()
    out = {k: d.get(k) for k in ("id", "mac", "ip", "hostname", "name", "owner", "type", "vendor", "notes",
                                  "first_seen", "last_seen", "last_dns", "paused_until", "ag_client_name")}
    out.update(
        display_name=display_name(d),
        is_online=bool(d.get("is_online")),
        is_private_mac=bool(d.get("is_private_mac")),
        is_self=bool(d.get("is_self")),
        is_gateway=bool(d.get("is_gateway")),
        trusted=bool(d.get("trusted")),
        paused=is_paused(d, now),
        paused_indefinitely=bool(d.get("paused")),
        controls=controls(d),
    )
    return out


def get(device_id: int) -> dict | None:
    return db.q1("SELECT * FROM devices WHERE id=?", (device_id,))


def save_controls(device_id: int, c: dict) -> None:
    db.ex("UPDATE devices SET controls=? WHERE id=?", (json.dumps(c), device_id))
