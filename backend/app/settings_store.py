"""Typed key/value settings stored in SQLite.

SCHEMA describes every user-editable setting (label, help text, type, default). The values the
app actually uses always come from the database, and the web UI edits them. Defaults only apply
until the user changes something.
"""
import json
import threading
import time

from . import db
from .config import DATA_DIR
from .security import protect, unprotect

# Your own defaults: a snapshot of settings saved from the Settings page. When present, every setting
# without its own value uses it instead of the built-in default (also on a fresh setup with this file in place).
DEFAULTS_FILE = DATA_DIR / "settings_defaults.json"

SCHEMA: list[dict] = [
    # ---- General
    dict(key="ui_bind_host", group="general", type="select", default="0.0.0.0",
         options=[{"value": "0.0.0.0", "label": "Whole home network (phones and laptops can open the dashboard)"},
                  {"value": "127.0.0.1", "label": "This PC only"}],
         label="Who can open the dashboard", restart=True,
         help="Choose 'Whole home network' to manage things from your phone. You'll still need the admin password."),
    dict(key="ui_port", group="general", type="int", default=8090, min=1024, max=65535,
         label="Dashboard port", restart=True, help="The port the dashboard runs on. Restart the app after changing it."),
    dict(key="session_hours", group="general", type="int", default=24, min=1, max=720,
         label="Stay signed in for (hours)", help="How long a login lasts before you have to sign in again."),
    dict(key="display_timezone", group="general", type="select", default="",
         options=[{"value": "", "label": "Automatic (this PC's timezone)"},
                  {"value": "Australia/Sydney", "label": "Sydney / Melbourne / Canberra (daylight saving)"},
                  {"value": "Australia/Brisbane", "label": "Brisbane (no daylight saving)"},
                  {"value": "Australia/Adelaide", "label": "Adelaide (daylight saving)"},
                  {"value": "Australia/Perth", "label": "Perth"},
                  {"value": "Australia/Darwin", "label": "Darwin"},
                  {"value": "Australia/Hobart", "label": "Hobart (daylight saving)"},
                  {"value": "Pacific/Auckland", "label": "Auckland (daylight saving)"},
                  {"value": "UTC", "label": "UTC"}],
         label="Dashboard timezone",
         help="Which timezone the clock and all times use. 'Automatic' follows this PC's clock. Pick your local "
              "zone if the PC is set to a different one than your modem (e.g. without daylight saving)."),

    # ---- Network scanning
    dict(key="scan_enabled", group="network", type="bool", default=True,
         label="Scan the network for devices", help="Finds every phone, tablet and computer on your Wi-Fi."),
    dict(key="scan_interface", group="network", type="interface", default="auto",
         label="Network adapter", help="The adapter connected to your home network. 'Auto' picks the one with internet access."),
    dict(key="scan_subnet", group="network", type="str", default="auto",
         label="Address range to scan", help="'auto' works it out from the adapter, or enter a range like 192.168.1.0/24."),
    dict(key="scan_interval_sec", group="network", type="int", default=120, min=30, max=3600,
         label="Scan every (seconds)", help="How often to check which devices are connected."),
    dict(key="probe_wait_sec", group="network", type="int", default=8, min=2, max=30,
         label="Wait for replies (seconds)", help="How long to wait for devices to answer each scan."),
    dict(key="offline_after_missed", group="network", type="int", default=3, min=1, max=20,
         label="Mark offline after missed scans", help="Phones nap to save battery. A higher number stops them flickering offline."),
    dict(key="max_scan_hosts", group="network", type="int", default=1024, min=16, max=65536,
         label="Max addresses per scan", help="Safety limit for very large address ranges."),
    dict(key="resolve_hostnames", group="network", type="bool", default=True,
         label="Look up device names", help="Asks the router for each device's name (e.g. 'Sams-iPhone')."),

    # ---- AdGuard Home
    dict(key="adguard_enabled", group="adguard", type="bool", default=False,
         label="Use AdGuard Home", help="Turn on once AdGuard Home is installed. It powers website and app tracking and blocking."),
    dict(key="adguard_url", group="adguard", type="str", default="http://127.0.0.1:3000",
         label="AdGuard Home address", help="The web address of AdGuard Home's admin page."),
    dict(key="adguard_username", group="adguard", type="str", default="",
         label="AdGuard username"),
    dict(key="adguard_password", group="adguard", type="password", default="", secret=True,
         label="AdGuard password", help="Stored encrypted with your Windows account (DPAPI)."),
    dict(key="adguard_poll_sec", group="adguard", type="int", default=30, min=5, max=600,
         label="Fetch activity every (seconds)"),
    dict(key="adguard_page_size", group="adguard", type="int", default=500, min=50, max=5000,
         label="Log entries per fetch"),
    dict(key="adguard_sync_clients", group="adguard", type="bool", default=True,
         label="Copy device names to AdGuard",
         help="Creates a named client in AdGuard for each device you name, so its logs are easy to read too."),
    dict(key="dns_online_window_min", group="adguard", type="int", default=5, min=1, max=60,
         label="Count as online if active in the last (minutes)",
         help="A device that looked up a website recently is treated as online even if it skipped a scan."),

    # ---- Usage tracking
    dict(key="usage_session_gap_min", group="usage", type="int", default=5, min=1, max=60,
         label="New session after a gap of (minutes)",
         help="Activity on the same app within this gap counts as one session."),
    dict(key="usage_min_session_sec", group="usage", type="int", default=60, min=0, max=900,
         label="Minimum session length (seconds)", help="Added to every session so a single visit still counts."),
    dict(key="usage_query_types", group="usage", type="str", default="A,AAAA,HTTPS",
         label="DNS record types to count", help="Comma-separated. The defaults cover normal web and app traffic."),
    dict(key="activity_detection", group="usage", type="bool", default=True,
         label="Only count time when someone is actually using the device",
         help="Ignores background traffic from locked phones and tablets (iCloud sync, app refresh, keep-alives)."),
    dict(key="activity_min_hosts", group="usage", type="int", default=3, min=1, max=50,
         label="In use if it reaches at least (different sites) in a window",
         help="A locked device repeats the same few background addresses. Someone using it reaches many different ones."),
    dict(key="activity_window_min", group="usage", type="int", default=5, min=1, max=30,
         label="Activity window (minutes)"),
    dict(key="activity_bridge_min", group="usage", type="int", default=10, min=0, max=60,
         label="Join in-use periods separated by less than (minutes)",
         help="So reading an article or watching a long video isn't split into pieces."),
    dict(key="activity_learn_background", group="usage", type="bool", default=True,
         label="Learn each device's background chatter",
         help="Addresses a device keeps contacting all day, used or not (e.g. a phone checking www.google.com every "
              "minute), are learned from the last 7 days and ignored when deciding if someone is using it. "
              "Until a device has a full day of history, only near-constant addresses are learned."),
    dict(key="retention_queries_days", group="usage", type="int", default=30, min=1, max=365,
         label="Keep detailed activity for (days)"),
    dict(key="retention_sessions_days", group="usage", type="int", default=365, min=7, max=3650,
         label="Keep usage history for (days)"),

    # ---- Alerts
    dict(key="alert_new_device", group="alerts", type="bool", default=True,
         label="Alert when a new device joins"),
    dict(key="alert_adguard_down", group="alerts", type="bool", default=True,
         label="Alert when AdGuard Home can't be reached"),
    dict(key="alert_paused_activity", group="alerts", type="bool", default=True,
         label="Alert when a paused device tries to go online"),

    # ---- DHCP (HomeNet's own address server)
    dict(key="dhcp_enabled", group="dhcp", type="bool", default=False,
         label="Hand out network addresses from this PC",
         help="Only turn this on after switching off DHCP on your modem. Two address servers on one network cause connection problems."),
    dict(key="dhcp_range_start", group="dhcp", type="str", default="auto",
         label="First address to hand out", help="'auto' uses .100 in your network (e.g. 192.168.1.100)."),
    dict(key="dhcp_range_end", group="dhcp", type="str", default="auto",
         label="Last address to hand out", help="'auto' uses .199. Keep fixed-IP devices (like this PC) outside this range."),
    dict(key="dhcp_lease_hours", group="dhcp", type="int", default=24, min=1, max=168,
         label="Lease length (hours)",
         help="How long a device keeps its address. Longer means devices stay online longer if this PC is off."),
    dict(key="dhcp_gateway", group="dhcp", type="str", default="auto",
         label="Gateway (router)", help="'auto' uses your modem's address."),
    dict(key="dhcp_dns", group="dhcp", type="str", default="auto",
         label="DNS servers", help="'auto' uses this PC, so lookups go through AdGuard Home. Adding others lets devices skip monitoring."),
    dict(key="dhcp_domain", group="dhcp", type="str", default="",
         label="Local domain name (optional)", help="e.g. 'home', so devices can be reached as name.home. Leave blank if unsure."),

    # ---- Automatic app detection
    dict(key="auto_detect_apps", group="detection", type="bool", default=True,
         label="Detect new apps and websites automatically",
         help="Any site HomeNet doesn't know becomes an app (e.g. gw.api.westpac.com.au → 'Westpac'). You can rename, recategorise or merge it later."),
    dict(key="auto_min_lookups", group="detection", type="int", default=5, min=1, max=1000,
         label="Create an app after this many lookups",
         help="A site must be looked up this many times (across all devices) before it becomes an app. This keeps one-off visits out."),
    dict(key="auto_min_session_lookups", group="detection", type="int", default=3, min=1, max=100,
         label="Ignore auto-detected visits shorter than (lookups)",
         help="Quick background check-ins to an auto-detected site don't count as screen time."),
    dict(key="adguard_catalog_sync", group="detection", type="bool", default=True,
         label="Use AdGuard's app list",
         help="Imports AdGuard Home's list of popular services (TikTok, Roblox, Netflix…) and keeps it up to date every day."),
    dict(key="psl_url", group="detection", type="str", default="https://publicsuffix.org/list/public_suffix_list.dat",
         label="Domain-ending list address",
         help="The public list of domain endings (.com.au, .co.uk…) used to work out which site an address belongs to. Refreshed monthly."),

    # ---- Vendor lookup
    dict(key="oui_url", group="vendor", type="str", default="https://standards-oui.ieee.org/oui/oui.csv",
         label="Manufacturer database address",
         help="The IEEE list used to show a device's maker (Apple, Samsung…)."),
]

INTERNAL_DEFAULTS = {
    "admin_password_hash": "",
    "token_secret": "",
    "setup_complete": False,
    "adguard_cursor_ns": 0,
    "managed_disallowed": [],
    "oui_updated": None,
}

_BY_KEY = {s["key"]: s for s in SCHEMA}
_cache: dict = {}
_lock = threading.Lock()


_saved: dict | None = None  # parsed DEFAULTS_FILE, {} when there is none


def portable_keys() -> list[str]:
    """Settings that can be saved as defaults / exported. Secrets (passwords) never leave the database."""
    return [s["key"] for s in SCHEMA if not s.get("secret")]


def validate_values(values: dict) -> tuple[dict, list[str]]:
    """Keep only known, non-secret settings with valid values. Returns (clean values, skipped keys)."""
    ok, skipped, allowed = {}, [], {*portable_keys()}  # this module's set() shadows the builtin
    for k, v in (values or {}).items():
        if k not in allowed:
            skipped.append(k)
            continue
        try:
            ok[k] = coerce(k, v)
        except (KeyError, ValueError, TypeError):
            skipped.append(k)
    return ok, skipped


APP_SOURCES = {"builtin", "adguard", "auto", "user"}


def validate_apps(apps) -> list[dict] | None:
    """Clean an 'Apps & categories' list from a defaults/export file. None if there is no usable list."""
    if not isinstance(apps, list):
        return None
    out, seen = [], {*()}  # empty set (this module's set() shadows the builtin)
    for a in apps:
        if not isinstance(a, dict):
            continue
        name, cat = str(a.get("name") or "").strip(), str(a.get("category") or "").strip()
        doms = a.get("domains")
        if not name or not cat or not isinstance(doms, list) or name.lower() in seen:
            continue
        doms = [d for d in dict.fromkeys(str(x).strip().lower().replace("https://", "").replace("http://", "")
                                         .split("/")[0].lstrip("*.").rstrip(".") for x in doms) if d]
        if not doms:
            continue
        seen.add(name.lower())
        out.append({"id": a.get("id") if isinstance(a.get("id"), int) else None, "name": name, "category": cat,
                    "domains": doms, "track_time": bool(a.get("track_time", True)), "hidden": bool(a.get("hidden", False)),
                    "source": a.get("source") if a.get("source") in APP_SOURCES else "user",
                    "reviewed": bool(a.get("reviewed", True)), "adguard_id": a.get("adguard_id") or None,
                    "registrable": a.get("registrable") or None})
    return out or None


def saved_defaults() -> dict:
    """{'saved': timestamp, 'settings': {...}, 'apps': [...] or None} from DEFAULTS_FILE, or {} if none / unreadable."""
    global _saved
    with _lock:
        if _saved is not None:
            return _saved
    data: dict = {}
    try:
        raw = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
        values, _ = validate_values(raw.get("settings") or {})
        data = {"saved": raw.get("saved"), "settings": values, "apps": validate_apps(raw.get("apps"))}
    except (OSError, ValueError, AttributeError):
        pass
    with _lock:
        _saved = data
    return data


def builtin_default(key):
    if key in _BY_KEY:
        return _BY_KEY[key]["default"]
    return INTERNAL_DEFAULTS.get(key)


def _default(key):
    own = saved_defaults().get("settings") or {}
    return own[key] if key in own else builtin_default(key)


def snapshot() -> dict:
    """Current value of every portable setting."""
    return {k: get(k) for k in portable_keys()}


def export_document(values: dict, apps: list[dict] | None = None) -> dict:
    doc = {"app": "HomeNet", "kind": "settings", "version": 2, "saved": time.time(), "settings": values}
    if apps:
        doc["apps"] = apps
    return doc


def save_defaults(values: dict | None = None, apps: list[dict] | None = None) -> dict:
    """Write values (default: the current settings) and optionally the app list as your own defaults.
    Current settings and apps don't change."""
    global _saved
    clean, _ = validate_values(snapshot() if values is None else values)
    _pin_current()
    doc = export_document(clean, validate_apps(apps))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DEFAULTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(DEFAULTS_FILE)
    with _lock:
        _saved = None
        _cache.clear()
    return doc


def clear_defaults() -> None:
    """Forget your own defaults; built-in ones apply again. Current settings don't change."""
    global _saved
    _pin_current()
    DEFAULTS_FILE.unlink(missing_ok=True)
    with _lock:
        _saved = None
        _cache.clear()


def differing_keys() -> list[str]:
    """Portable settings whose current value differs from the default (yours, else built-in)."""
    return [k for k in portable_keys() if get(k) != _default(k)]


def _pin_current() -> None:
    """Store an explicit value for every portable setting still following a default, so changing or removing
    the defaults file never silently changes live settings."""
    have = {r["key"] for r in db.q("SELECT key FROM settings")}
    for k in portable_keys():
        if k not in have:
            set(k, get(k))


def reset_to_defaults() -> list[str]:
    """Set every portable setting to its default (yours if saved, else built-in). Returns the keys that changed."""
    changed = differing_keys()
    for k in portable_keys():
        set(k, _default(k))
    return changed


def get(key: str):
    with _lock:
        if key in _cache:
            return _cache[key]
    row = db.q1("SELECT value FROM settings WHERE key=?", (key,))
    value = _default(key) if row is None else db.jload(row["value"], _default(key))
    if key in _BY_KEY and _BY_KEY[key].get("secret"):
        value = unprotect(value) if value else ""
    with _lock:
        _cache[key] = value
    return value


def set(key: str, value) -> None:  # noqa: A001 - mirrors get()
    stored = value
    if key in _BY_KEY and _BY_KEY[key].get("secret"):
        stored = protect(value) if value else ""
    db.ex("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
          (key, json.dumps(stored)))
    with _lock:
        _cache[key] = value


def coerce(key: str, value):
    spec = _BY_KEY.get(key)
    if spec is None:
        raise KeyError(key)
    t = spec["type"]
    if t == "bool":
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if t == "int":
        v = int(value)
        if "min" in spec and v < spec["min"]:
            raise ValueError(f"{spec['label']} must be at least {spec['min']}")
        if "max" in spec and v > spec["max"]:
            raise ValueError(f"{spec['label']} must be at most {spec['max']}")
        return v
    if t == "select":
        v = str(value)
        if v not in [o["value"] for o in spec["options"]]:
            raise ValueError(f"Invalid choice for {spec['label']}")
        return v
    return str(value).strip()


def public_view() -> list[dict]:
    """Schema plus current values for the settings screen. Secrets are never returned."""
    out = []
    for spec in SCHEMA:
        item = {k: v for k, v in spec.items()}
        if spec.get("secret"):
            item["value"] = ""
            item["has_value"] = bool(get(spec["key"]))
        else:
            item["value"] = get(spec["key"])
        out.append(item)
    return out


def is_editable(key: str) -> bool:
    return key in _BY_KEY
