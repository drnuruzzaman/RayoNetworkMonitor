"""Read Windows network adapter and neighbour (ARP/NDP) tables via PowerShell."""
import ipaddress
import json
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_PS_INTERFACES = r"""
$out = foreach ($c in Get-NetIPConfiguration) {
  if (-not $c.NetAdapter -or $c.NetAdapter.Status -ne 'Up') { continue }
  $gw = $null
  if ($c.IPv4DefaultGateway) { $gw = @($c.IPv4DefaultGateway)[0].NextHop }
  foreach ($a in @($c.IPv4Address)) {
    if (-not $a -or $a.IPAddress -like '169.254.*') { continue }
    [pscustomobject]@{
      alias = $c.InterfaceAlias; index = $c.InterfaceIndex; ip = $a.IPAddress;
      prefix = [int]$a.PrefixLength; gateway = $gw; mac = $c.NetAdapter.MacAddress;
      description = $c.InterfaceDescription; origin = $a.PrefixOrigin.ToString()
    }
  }
}
ConvertTo-Json -InputObject @($out) -Compress
"""

_PS_NEIGHBOURS = r"""
$n = Get-NetNeighbor -InterfaceIndex {idx} -ErrorAction SilentlyContinue | ForEach-Object {{
  [pscustomobject]@{{ ip = $_.IPAddress; mac = $_.LinkLayerAddress; state = $_.State.ToString(); family = $_.AddressFamily.ToString() }}
}}
ConvertTo-Json -InputObject @($n) -Compress
"""


def _ps(script: str, timeout: int = 30):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "PowerShell failed").strip()[:500])
    out = (r.stdout or "").strip()
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def norm_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    m = mac.replace("-", "").replace(":", "").replace(".", "").lower()
    if len(m) != 12:
        return None
    return ":".join(m[i:i + 2] for i in range(0, 12, 2))


def is_private_mac(mac: str) -> bool:
    """Locally administered bit set: iOS/Android/Windows 'private' or randomised addresses."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except Exception:
        return False


def _bad_mac(mac: str | None) -> bool:
    if not mac:
        return True
    first = int(mac.split(":")[0], 16)
    return mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") or bool(first & 0x01)


def list_interfaces() -> list[dict]:
    items = _ps(_PS_INTERFACES)
    for i in items:
        i["mac"] = norm_mac(i.get("mac"))
        try:
            i["network"] = str(ipaddress.ip_interface(f"{i['ip']}/{i['prefix']}").network)
        except ValueError:
            i["network"] = None
    # Interfaces with a default gateway first; VPN/virtual adapters last.
    virtual = ("vpn", "tap", "virtual", "hyper-v", "vethernet", "wsl", "loopback", "tunnel")
    items.sort(key=lambda i: (i.get("gateway") is None,
                              any(v in f"{i.get('alias','')} {i.get('description','')}".lower() for v in virtual)))
    return items


def pick_interface(choice: str) -> dict | None:
    items = list_interfaces()
    if not items:
        return None
    if choice and choice != "auto":
        for i in items:
            if i["alias"] == choice:
                return i
    return items[0]


def neighbours(index: int) -> list[dict]:
    rows = _ps(_PS_NEIGHBOURS.format(idx=int(index)))
    out = []
    for r in rows:
        mac = norm_mac(r.get("mac"))
        if _bad_mac(mac):
            continue
        ip = r.get("ip") or ""
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            continue
        if addr.is_multicast or addr.is_unspecified or str(addr).endswith(".255"):
            continue
        out.append({"ip": str(addr), "mac": mac, "state": r.get("state"), "family": r.get("family")})
    return out
