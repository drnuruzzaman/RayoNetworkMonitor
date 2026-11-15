"""Setup check: finds the common reasons other devices' activity isn't being tracked."""
import asyncio
import time

from . import db, netinfo
from . import devices as D
from . import settings_store as S
from .state import STATUS

_PS_HOST = r"""
$alias = '{alias}'
$p = Get-NetConnectionProfile -InterfaceAlias $alias -ErrorAction SilentlyContinue | Select-Object -First 1
$cat = $null; $net = $null
if ($p) {{ $cat = $p.NetworkCategory.ToString(); $net = $p.Name }}
$rules = @()
# Fast path: the rules our installer creates. Slow path (no admin needed): search all inbound allow rules.
$cand = @(Get-NetFirewallRule -DisplayName 'AdGuard Home DNS*' -ErrorAction SilentlyContinue | Where-Object {{ $_.Enabled.ToString() -eq 'True' }})
if (-not $cand) {{
  $all = Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue
  $cand = @($all | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue | Where-Object {{ $_.Protocol -eq 'UDP' -and @($_.LocalPort) -contains '53' }} | Get-NetFirewallRule -ErrorAction SilentlyContinue)
  $cand += @($all | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue | Where-Object {{ $_.Program -like '*AdGuardHome.exe' }} | Get-NetFirewallRule -ErrorAction SilentlyContinue)
}}
foreach ($r in $cand) {{
  if ($r -and $r.Enabled.ToString() -eq 'True' -and $r.Direction.ToString() -eq 'Inbound' -and $r.Action.ToString() -eq 'Allow') {{
    $rules += [pscustomobject]@{{ name = $r.DisplayName; profile = $r.Profile.ToString() }}
  }}
}}
$v6 = @((Get-DnsClientServerAddress -InterfaceAlias $alias -AddressFamily IPv6 -ErrorAction SilentlyContinue).ServerAddresses)
$v4 = @((Get-DnsClientServerAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses)
[pscustomobject]@{{ category = $cat; network = $net; rules = @($rules); ipv6_dns = @($v6); ipv4_dns = @($v4) }} | ConvertTo-Json -Compress -Depth 4
"""

_cache: dict = {"ts": 0.0, "data": None}


def _check(id_, status, title, detail, fix=None, link=None):
    return {"id": id_, "status": status, "title": title, "detail": detail, "fix": fix, "link": link}


def _host_checks(alias: str) -> list[dict]:
    try:
        info = netinfo._ps(_PS_HOST.format(alias=alias.replace("'", "''")), timeout=60)[0]
    except Exception as e:
        return [_check("host", "unknown", "Couldn't check Windows network settings", str(e)[:300])]
    out = []
    cat = info.get("category")
    name = info.get("network") or alias
    if cat is None:
        out.append(_check("profile", "unknown", "Network type unknown", f"Couldn't read the network type for {alias}."))
    elif cat == "Public":
        out.append(_check("profile", "error", "Windows treats your Wi-Fi as a public network",
                          f"'{name}' is set to Public, so Windows Firewall blocks other devices from reaching AdGuard Home and the dashboard.",
                          f"Settings → Network & internet → Wi-Fi → {name} → Network profile type → Private network."))
    else:
        out.append(_check("profile", "ok", "Network is set to Private", f"'{name}' is a {cat} network."))

    cat_name = {"DomainAuthenticated": "Domain"}.get(cat, cat)
    rules = info.get("rules") or []
    covering = [r for r in rules if r.get("profile") == "Any" or (cat_name and cat_name in (r.get("profile") or ""))]
    if covering:
        out.append(_check("firewall", "ok", "Firewall allows DNS from other devices",
                          f"Allowed by: {', '.join(sorted({r['name'] for r in covering}))}."))
    elif rules:
        profiles = ", ".join(sorted({r["profile"] for r in rules}))
        out.append(_check("firewall", "warn" if cat == "Public" else "error", "Firewall rule doesn't cover this network",
                          f"DNS is only allowed on {profiles} networks, but this network is {cat}.",
                          "Set the Wi-Fi to Private (see above). That's the safest fix."))
    else:
        out.append(_check("firewall", "error", "No firewall rule lets devices reach AdGuard Home",
                          "Other devices' DNS requests to this PC are blocked by Windows Firewall.",
                          "Run scripts\\install-adguard.ps1 again from an Administrator PowerShell. It adds the rules."))

    from .state import STATUS
    my_ip = (STATUS["scan"].get("interface") or {}).get("ip")
    v4 = [a for a in (info.get("ipv4_dns") or []) if a]
    if v4 and my_ip and not any(a in (my_ip, "127.0.0.1") for a in v4):
        out.append(_check("pc_dns", "warn", "This PC isn't using AdGuard Home",
                          f"Windows sends this PC's lookups to {', '.join(v4)}, not to AdGuard, so its own activity isn't tracked per device.",
                          f"Windows Settings → Network & internet → Wi-Fi → Hardware properties → DNS server assignment → Edit → Manual → Preferred DNS {my_ip}."))
    elif v4:
        out.append(_check("pc_dns", "ok", "This PC uses AdGuard Home", f"DNS: {', '.join(v4)}."))

    v6 = [a for a in (info.get("ipv6_dns") or []) if a and not a.lower().startswith("fec0:0:0:ffff::") and a != "::1"]
    if v6:
        now = time.time()
        # Phones/tablets/computers that are online but AdGuard hasn't seen in the last hour: the likely bypassers.
        human = db.q("SELECT * FROM devices WHERE is_online=1 AND is_self=0 AND is_gateway=0 "
                     "AND type IN ('phone','tablet','computer','laptop')")
        candidates = [D.display_name(d) for d in human if not (d["last_dns"] and now - d["last_dns"] < 3600)]
        detail = (f"This PC was given {', '.join(v6)} as an IPv6 DNS server. Phones and tablets often prefer IPv6, "
                  "so they can skip AdGuard Home. HomeNet can't see a device that fully bypasses it, so it can only "
                  "point to likely ones: devices online now that AdGuard hasn't seen in the last hour.")
        if candidates:
            shown = ", ".join(candidates[:6]) + (f" and {len(candidates) - 6} more" if len(candidates) > 6 else "")
            detail += f" Right now that's: {shown}. (Could also be a VPN, Private DNS or iCloud Private Relay, not only IPv6.)"
        else:
            detail += " Right now every online phone, tablet and computer is reaching AdGuard, so none appears to be bypassing."
        out.append(_check("ipv6", "warn", "Your modem hands out its own IPv6 DNS server", detail,
                          "In the modem's IPv6 / LAN settings, turn off IPv6 DNS (RDNSS / DHCPv6 DNS) or point it at this PC, or turn IPv6 off on the LAN.",
                          "/devices"))
    else:
        out.append(_check("ipv6", "ok", "No IPv6 DNS bypass detected", "This PC wasn't given an IPv6 DNS server by the modem."))
    return out


def _relay_check() -> dict | None:
    """Lookups arriving *from the router* mean devices ask the modem, which forwards to AdGuard.
    They're filtered, but all look like one client, so per-device tracking and pausing can't work for them."""
    from .state import STATUS
    gw = (STATUS["scan"].get("interface") or {}).get("gateway")
    if not gw:
        return None
    now = time.time()
    n = db.val("SELECT COUNT(*) FROM dns_queries WHERE client=? AND ts>?", (gw, now - 3600)) or 0
    if not n:
        return _check("relay", "ok", "No lookups relayed through the modem", "Every lookup AdGuard sees comes straight from a device.")
    total = db.val("SELECT COUNT(*) FROM dns_queries WHERE ts>?", (now - 3600,)) or n
    pct = round(100 * n / total)
    return _check("relay", "warn", "Some devices reach AdGuard through your modem",
                  f"{n} lookups in the last hour ({pct}%) came from the modem ({gw}) on behalf of other devices. "
                  "They're filtered, but HomeNet can't tell which device made them, so it can't track or pause those devices.",
                  "Point devices straight at this PC instead: HomeNet's Address server, or DNS set on each device.", "/dhcp")


def _coverage_check() -> dict:
    now = time.time()
    window = 3600
    devs = [d for d in db.q("SELECT * FROM devices WHERE is_online=1 AND is_self=0 AND is_gateway=0")]
    if not devs:
        return _check("coverage", "unknown", "No other devices online", "Connect a phone or tablet to check whether its activity is tracked.")
    covered = [d for d in devs if d["last_dns"] and now - d["last_dns"] < window]
    missing = [D.display_name(d) for d in devs if d not in covered]
    if not covered:
        return _check("coverage", "error", "No other device is using AdGuard Home",
                      f"None of the {len(devs)} online devices has sent AdGuard a lookup in the last hour. Only this PC is being tracked.",
                      "Set the modem's DHCP DNS server to this PC. If the modem won't allow that, use HomeNet's address server instead.",
                      "/dhcp")
    if missing:
        shown = ", ".join(missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
        return _check("coverage", "warn", f"{len(covered)} of {len(devs)} online devices are tracked",
                      f"Not seen in AdGuard in the last hour: {shown}. Smart-home gadgets may just be idle.",
                      "For phones and laptops in that list, check their DNS settings, and turn off Private DNS, iCloud Private Relay or any VPN.",
                      "/settings/guide")
    return _check("coverage", "ok", "All online devices are tracked", f"All {len(devs)} online devices used AdGuard Home in the last hour.")


def _dhcp_checks() -> list[dict]:
    from . import dhcp
    if not S.get("dhcp_enabled"):
        return []
    out = []
    st = dhcp.SERVER.status
    if st["running"]:
        out.append(_check("dhcp", "ok", "Address server is running", f"Handing out addresses on {st['config']['interface']}."))
    else:
        out.append(_check("dhcp", "error", "Address server isn't running", st.get("error") or "Starting…",
                          "Open the Address server page for details.", "/dhcp"))
    others = dhcp.SERVER.other_servers()
    if others:
        out.append(_check("dhcp_other", "error", "Another DHCP server is still active",
                          f"Devices are still getting addresses from {', '.join(o['ip'] for o in others)}. Two servers on one network cause dropouts.",
                          "Turn off DHCP on your modem, or turn off HomeNet's address server.", "/dhcp"))
    fw = dhcp.firewall_status()
    if fw.get("ok") is False:
        out.append(_check("dhcp_fw", "error", "Firewall blocks the address server",
                          "Devices can't reach this PC on UDP port 67.",
                          "Run scripts\\allow-dhcp-firewall.ps1 from an Administrator PowerShell.", "/dhcp"))
    return out


async def run(force: bool = False) -> dict:
    if not force and _cache["data"] and time.time() - _cache["ts"] < 120:
        return _cache["data"]
    checks = []
    if not S.get("adguard_enabled"):
        checks.append(_check("adguard", "error", "AdGuard Home isn't connected",
                             "App activity, pausing and blocking all need AdGuard Home.",
                             "Install it, then connect it in Settings → AdGuard Home.", "/settings/adguard"))
    elif STATUS["adguard"]["ok"] is False:
        checks.append(_check("adguard", "error", "Can't reach AdGuard Home", STATUS["adguard"]["error"] or "",
                             "Check the address, username and password in Settings → AdGuard Home.", "/settings/adguard"))
    else:
        checks.append(_check("adguard", "ok", "Connected to AdGuard Home", S.get("adguard_url")))

    alias = (STATUS["scan"].get("interface") or {}).get("alias")
    if not alias:
        iface = await asyncio.to_thread(netinfo.pick_interface, S.get("scan_interface"))
        alias = iface["alias"] if iface else None
    if alias:
        checks += await asyncio.to_thread(_host_checks, alias)
    if S.get("adguard_enabled"):
        checks.append(_coverage_check())
        relay = _relay_check()
        if relay:
            checks.append(relay)
    checks += await asyncio.to_thread(_dhcp_checks)

    order = {"error": 0, "warn": 1, "unknown": 2, "ok": 3}
    checks.sort(key=lambda c: order[c["status"]])
    data = {"checks": checks, "problems": sum(c["status"] in ("error", "warn") for c in checks), "checked": time.time()}
    _cache.update(ts=time.time(), data=data)
    return data
