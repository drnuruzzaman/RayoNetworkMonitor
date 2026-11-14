"""HomeNet's own DHCPv4 server.

Why: AdGuard Home's DHCP server isn't supported on Windows, and many ISP modems (including
TPG's) won't let you change the DNS server they hand out. If the modem lets you switch its DHCP
*off*, HomeNet can hand out addresses instead and point every device's DNS at this PC.

Safety:
* Off by default. Enabling needs a static IP on this PC (checked).
* It never offers an address seen in use by another device, the gateway or this PC.
* It watches for other DHCP servers and reports them (two servers on one LAN cause trouble).
* Leases are long (24h default), so devices stay online for a while even if HomeNet stops.
"""
import ipaddress
import logging
from collections import deque
import os
import socket
import struct
import threading
import time

from . import db, netinfo
from . import settings_store as S

log = logging.getLogger("homenet.dhcp")

SERVER_PORT, CLIENT_PORT = 67, 68
MAGIC = b"\x63\x82\x53\x63"
DISCOVER, OFFER, REQUEST, DECLINE, ACK, NAK, RELEASE, INFORM = 1, 2, 3, 4, 5, 6, 7, 8
MSG_NAMES = {1: "DISCOVER", 2: "OFFER", 3: "REQUEST", 4: "DECLINE", 5: "ACK", 6: "NAK", 7: "RELEASE", 8: "INFORM"}
OFFER_HOLD_SEC = 60
DECLINE_HOLD_SEC = 600


class ConfigError(ValueError):
    pass


# ====================================================================== config
_iface_cache: dict = {"ts": 0.0, "iface": None}


def _resolve_iface() -> dict:
    from .state import STATUS
    iface = STATUS["scan"].get("interface")
    if not iface or not iface.get("origin") or not iface.get("mac"):
        if _iface_cache["iface"] and time.time() - _iface_cache["ts"] < 120:
            iface = _iface_cache["iface"]
        else:
            iface = netinfo.pick_interface(S.get("scan_interface"))
            _iface_cache.update(ts=time.time(), iface=iface)
    if not iface:
        raise ConfigError("No active network adapter found.")
    return iface


def build_config(overrides: dict | None = None, iface: dict | None = None) -> dict:
    """Work out the effective DHCP settings. Raises ConfigError with a friendly message."""
    o = overrides or {}
    get = lambda k: o[k] if k in o else S.get(k)  # noqa: E731
    iface = iface or _resolve_iface()
    server = ipaddress.ip_address(iface["ip"])
    net = ipaddress.ip_network(f"{iface['ip']}/{iface['prefix']}", strict=False)

    def addr(value, label):
        try:
            a = ipaddress.ip_address(str(value).strip())
        except ValueError:
            raise ConfigError(f"{label} '{value}' isn't a valid IPv4 address.")
        if a not in net:
            raise ConfigError(f"{label} {a} isn't inside your network {net}.")
        return a

    hosts_n = net.num_addresses - 2
    if hosts_n < 8:
        raise ConfigError(f"Your network {net} is too small for an address server.")
    base = int(net.network_address)
    auto_start = base + (100 if hosts_n >= 254 else max(2, hosts_n // 3))
    auto_end = base + (199 if hosts_n >= 254 else max(3, (hosts_n * 2) // 3))
    start = addr(get("dhcp_range_start"), "First address") if get("dhcp_range_start") not in ("", "auto") else ipaddress.ip_address(auto_start)
    end = addr(get("dhcp_range_end"), "Last address") if get("dhcp_range_end") not in ("", "auto") else ipaddress.ip_address(auto_end)
    if int(end) < int(start):
        raise ConfigError("The last address must come after the first address.")
    if int(end) - int(start) > 4096:
        raise ConfigError("That address range is too large (max 4096 addresses).")

    gw_setting = get("dhcp_gateway")
    if gw_setting in ("", "auto"):
        if not iface.get("gateway"):
            raise ConfigError("Couldn't find your router's address. Enter the gateway manually.")
        gateway = ipaddress.ip_address(iface["gateway"])
    else:
        gateway = addr(gw_setting, "Gateway")

    dns_setting = (get("dhcp_dns") or "auto").strip()
    if dns_setting == "auto":
        dns = [server]
    else:
        dns = []
        for part in dns_setting.replace(";", ",").split(","):
            if part.strip():
                try:
                    dns.append(ipaddress.ip_address(part.strip()))
                except ValueError:
                    raise ConfigError(f"DNS server '{part.strip()}' isn't a valid IPv4 address.")
        if not dns:
            raise ConfigError("Enter at least one DNS server, or 'auto'.")

    if start <= server <= end:
        raise ConfigError(f"This PC's address {server} is inside the range. Choose a range that doesn't include it.")
    if start <= gateway <= end:
        raise ConfigError(f"The router's address {gateway} is inside the range. Choose a range that doesn't include it.")

    return {
        "interface": iface["alias"],
        "server_ip": str(server),
        "static_ip": iface.get("origin") == "Manual",
        "network": str(net),
        "netmask": str(net.netmask),
        "broadcast": str(net.broadcast_address),
        "range_start": str(start),
        "range_end": str(end),
        "gateway": str(gateway),
        "dns": [str(d) for d in dns],
        "lease_sec": int(get("dhcp_lease_hours")) * 3600,
        "domain": (get("dhcp_domain") or "").strip(),
    }


# ====================================================================== packets
def parse(data: bytes) -> dict | None:
    if len(data) < 240 or data[236:240] != MAGIC:
        return None
    op, htype, hlen = data[0], data[1], data[2]
    pkt = {
        "op": op, "htype": htype, "hlen": hlen,
        "xid": data[4:8], "flags": data[10:12],
        "ciaddr": socket.inet_ntoa(data[12:16]), "yiaddr": socket.inet_ntoa(data[16:20]),
        "giaddr": socket.inet_ntoa(data[24:28]), "chaddr": data[28:44],
        "mac": ":".join(f"{b:02x}" for b in data[28:28 + min(hlen, 16)]),
        "options": {},
    }
    i, opts = 240, pkt["options"]
    while i < len(data):
        code = data[i]
        if code == 255:
            break
        if code == 0:
            i += 1
            continue
        if i + 1 >= len(data):
            break
        ln = data[i + 1]
        opts[code] = data[i + 2:i + 2 + ln]
        i += 2 + ln
    mt = opts.get(53)
    pkt["type"] = mt[0] if mt else None
    if 50 in opts and len(opts[50]) == 4:
        pkt["requested"] = socket.inet_ntoa(opts[50])
    if 54 in opts and len(opts[54]) == 4:
        pkt["server_id"] = socket.inet_ntoa(opts[54])
    if 12 in opts:
        pkt["hostname"] = opts[12].decode("utf-8", "replace").strip("\x00").strip()[:63] or None
    return pkt


def _opt(code: int, value: bytes) -> bytes:
    return bytes([code, len(value)]) + value


def build_reply(req: dict, msg_type: int, cfg: dict, yiaddr: str = "0.0.0.0", ciaddr: str = "0.0.0.0") -> bytes:
    pkt = bytearray(240)
    pkt[0], pkt[1], pkt[2] = 2, 1, 6
    pkt[4:8] = req["xid"]
    pkt[10:12] = req["flags"]
    pkt[12:16] = socket.inet_aton(ciaddr)
    pkt[16:20] = socket.inet_aton(yiaddr)
    pkt[24:28] = socket.inet_aton(req["giaddr"])
    pkt[28:44] = req["chaddr"]
    pkt[236:240] = MAGIC
    opts = _opt(53, bytes([msg_type])) + _opt(54, socket.inet_aton(cfg["server_ip"]))
    if msg_type != NAK:
        if msg_type != ACK or req["type"] != INFORM:
            lease = cfg["lease_sec"]
            opts += _opt(51, struct.pack("!I", lease)) + _opt(58, struct.pack("!I", lease // 2)) + _opt(59, struct.pack("!I", lease * 7 // 8))
        opts += _opt(1, socket.inet_aton(cfg["netmask"]))
        opts += _opt(3, socket.inet_aton(cfg["gateway"]))
        opts += _opt(6, b"".join(socket.inet_aton(d) for d in cfg["dns"]))
        opts += _opt(28, socket.inet_aton(cfg["broadcast"]))
        if cfg.get("domain"):
            opts += _opt(15, cfg["domain"].encode()[:63])
    else:
        opts += _opt(56, b"Address not available")
    return bytes(pkt) + opts + b"\xff"


# ====================================================================== lease logic
class LeaseLogic:
    """Pure decision-making. Storage goes through db; no sockets here, so it can be unit-tested."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.net = ipaddress.ip_network(cfg["network"])
        self.start = int(ipaddress.ip_address(cfg["range_start"]))
        self.end = int(ipaddress.ip_address(cfg["range_end"]))
        self.special = {cfg["server_ip"], cfg["gateway"], str(self.net.network_address), str(self.net.broadcast_address)}
        self.offers: dict[str, tuple[str, float]] = {}
        self.declined: dict[str, float] = {}

    def in_range(self, ip: str) -> bool:
        return self.start <= int(ipaddress.ip_address(ip)) <= self.end

    def in_subnet(self, ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip) in self.net
        except ValueError:
            return False

    def static_for(self, mac: str) -> str | None:
        r = db.q1("SELECT ip FROM dhcp_leases WHERE mac=? AND static=1", (mac,))
        return r["ip"] if r else None

    def taken_by_other(self, ip: str, mac: str, now: float) -> bool:
        if ip in self.special:
            return True
        if self.declined.get(ip, 0) > now:
            return True
        if db.q1("SELECT 1 FROM dhcp_leases WHERE ip=? AND mac!=? AND (static=1 OR expires>?)", (ip, mac, now)):
            return True
        for other, (oip, exp) in self.offers.items():
            if other != mac and oip == ip and exp > now:
                return True
        # Live evidence from the network scanner: another MAC answered on this IP in the last hour.
        if db.q1("SELECT 1 FROM device_ips di JOIN devices d ON d.id=di.device_id "
                 "WHERE di.ip=? AND d.mac!=? AND di.last_seen>?", (ip, mac, now - 3600)):
            return True
        return False

    def known_ip_for(self, mac: str) -> str | None:
        """The address this device had before (e.g. from the modem), so it can keep it."""
        d = db.q1("SELECT ip FROM devices WHERE mac=?", (mac,))
        return d["ip"] if d and d["ip"] else None

    def verdict(self, mac: str, ip: str, now: float) -> str:
        """'ok' = may use it, 'conflict' = definitely wrong (send NAK), 'unknown' = not ours to judge (stay silent)."""
        if not self.in_subnet(ip):
            return "conflict"
        static = self.static_for(mac)
        if static:
            return "ok" if static == ip else "conflict"
        if self.taken_by_other(ip, mac, now):
            return "conflict"
        if self.in_range(ip):
            return "ok"
        # Outside the pool: only allow it if this device already had it (smooth switch-over from the modem).
        lease = db.q1("SELECT ip FROM dhcp_leases WHERE mac=?", (mac,))
        if ip in {self.known_ip_for(mac), lease["ip"] if lease else None}:
            return "ok"
        return "unknown"

    def acceptable(self, mac: str, ip: str, now: float) -> bool:
        return self.verdict(mac, ip, now) == "ok"

    def choose(self, mac: str, requested: str | None, now: float) -> str | None:
        static = self.static_for(mac)
        if static:
            return static
        offer = self.offers.get(mac)
        if offer and offer[1] > now and self.acceptable(mac, offer[0], now):
            return offer[0]
        lease = db.q1("SELECT ip FROM dhcp_leases WHERE mac=?", (mac,))
        for cand in (lease["ip"] if lease else None, requested, self.known_ip_for(mac)):
            if cand and self.acceptable(mac, cand, now):
                return cand
        for n in range(self.start, self.end + 1):
            ip = str(ipaddress.ip_address(n))
            if not self.taken_by_other(ip, mac, now):
                return ip
        return None

    def commit(self, mac: str, ip: str, hostname: str | None, now: float) -> None:
        exp = now + self.cfg["lease_sec"]
        db.ex("""INSERT INTO dhcp_leases(mac, ip, hostname, expires, static, updated) VALUES(?,?,?,?,0,?)
                 ON CONFLICT(mac) DO UPDATE SET ip=excluded.ip, hostname=COALESCE(excluded.hostname, dhcp_leases.hostname),
                 expires=excluded.expires, updated=excluded.updated""", (mac, ip, hostname, exp, now))
        self.offers.pop(mac, None)
        d = db.q1("SELECT id, hostname FROM devices WHERE mac=?", (mac,))
        if d:
            db.ex("UPDATE devices SET ip=? WHERE id=?", (ip, d["id"]))
            if hostname and not d["hostname"]:
                db.ex("UPDATE devices SET hostname=? WHERE id=?", (hostname, d["id"]))
            db.ex("""INSERT INTO device_ips(ip, device_id, last_seen) VALUES(?,?,?)
                     ON CONFLICT(ip) DO UPDATE SET device_id=excluded.device_id, last_seen=excluded.last_seen""", (ip, d["id"], now))

    def handle(self, pkt: dict, now: float | None = None, stats: dict | None = None) -> tuple[bytes, str] | None:
        """Returns (reply, destination_ip) or None to stay silent."""
        now = now or time.time()
        stats = stats if stats is not None else {}
        if pkt["op"] != 1 or pkt["htype"] != 1 or pkt["hlen"] != 6 or pkt["giaddr"] != "0.0.0.0":
            return None
        mac, t = pkt["mac"], pkt["type"]
        stats[MSG_NAMES.get(t, "OTHER")] = stats.get(MSG_NAMES.get(t, "OTHER"), 0) + 1
        bcast = "255.255.255.255"

        if t == DISCOVER:
            ip = self.choose(mac, pkt.get("requested"), now)
            if not ip:
                log.warning("DHCP pool exhausted, no address for %s", mac)
                stats["exhausted"] = stats.get("exhausted", 0) + 1
                return None
            self.offers[mac] = (ip, now + OFFER_HOLD_SEC)
            return build_reply(pkt, OFFER, self.cfg, yiaddr=ip), bcast

        if t == REQUEST:
            sid = pkt.get("server_id")
            if sid and sid != self.cfg["server_ip"]:
                # The device picked another DHCP server.
                self.offers.pop(mac, None)
                stats.setdefault("other_servers", {})[sid] = now
                return None
            selecting = sid == self.cfg["server_ip"]
            if pkt["ciaddr"] != "0.0.0.0" and not pkt.get("requested"):
                ip, dest = pkt["ciaddr"], pkt["ciaddr"]          # renewing / rebinding
            else:
                ip, dest = pkt.get("requested"), bcast           # selecting / init-reboot
            if not ip:
                return None
            v = self.verdict(mac, ip, now)
            if v == "ok":
                self.commit(mac, ip, pkt.get("hostname"), now)
                return build_reply(pkt, ACK, self.cfg, yiaddr=ip, ciaddr=pkt["ciaddr"]), dest
            if v == "conflict" or selecting:
                stats["NAK_sent"] = stats.get("NAK_sent", 0) + 1
                return build_reply(pkt, NAK, self.cfg), bcast
            return None  # not ours to refuse (may be a lease from another server)

        if t == DECLINE:
            ip = pkt.get("requested")
            if ip:
                self.declined[ip] = now + DECLINE_HOLD_SEC
                db.ex("UPDATE dhcp_leases SET expires=? WHERE mac=? AND ip=? AND static=0", (now, mac, ip))
            self.offers.pop(mac, None)
            return None

        if t == RELEASE:
            db.ex("UPDATE dhcp_leases SET expires=? WHERE mac=? AND static=0", (now, mac))
            return None

        if t == INFORM and pkt["ciaddr"] != "0.0.0.0":
            return build_reply(pkt, ACK, self.cfg, ciaddr=pkt["ciaddr"]), pkt["ciaddr"]
        return None


# ====================================================================== server thread
class DhcpServer:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.cfg: dict | None = None
        self.logic: LeaseLogic | None = None
        self.status = {"running": False, "error": None, "started": None, "last_packet": None, "stats": {}, "config": None}
        self.events: deque = deque(maxlen=80)

    def ensure(self) -> None:
        """Start, stop or restart to match the saved settings. Called every few seconds."""
        if not S.get("dhcp_enabled"):
            if self._thread:
                self.stop()
            self.status.update(error=None)
            return
        try:
            cfg = build_config()
            if not cfg["static_ip"]:
                raise ConfigError("This PC's IP address isn't static. Set a fixed IP in Windows before using the address server.")
        except Exception as e:
            self.status.update(error=str(e))
            if self._thread:
                self.stop()
            return
        if self._thread and self._thread.is_alive() and cfg == self.cfg:
            return
        if self._thread:
            self.stop()
        self.start(cfg)

    def start(self, cfg: dict) -> None:
        self._stop.clear()
        self.cfg = cfg
        self.logic = LeaseLogic(cfg)
        self.status.update(config=cfg, error=None)
        self._thread = threading.Thread(target=self._run, args=(cfg,), name="homenet-dhcp", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        self.status.update(running=False)

    # ------------------------------------------------------------ activity log
    def event(self, text: str, level: str = "info", mac: str | None = None) -> None:
        self.events.appendleft({"ts": time.time(), "level": level, "text": text, "mac": mac})
        (log.warning if level in ("warn", "error") else log.info)("DHCP: %s", text)

    def _describe(self, pkt: dict, out) -> None:
        from . import devices as D
        mac = pkt["mac"]
        row = db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
        who = D.display_name(row) if row else (pkt.get("hostname") or mac)
        t = pkt["type"]
        rtype = parse(out[0])["type"] if out else None
        if t == DISCOVER:
            self.event(f"{who} asked for an address → offered {parse(out[0])['yiaddr']}" if out
                       else f"{who} asked for an address → none free!", "info" if out else "error", mac)
        elif t == REQUEST:
            ip = pkt.get("requested") or pkt["ciaddr"]
            if rtype == ACK:
                self.event(f"{who} got {ip}", "success", mac)
            elif rtype == NAK:
                self.event(f"{who} asked for {ip} → refused (conflict or wrong network)", "warn", mac)
            elif pkt.get("server_id") and pkt["server_id"] != (self.cfg or {}).get("server_ip"):
                self.event(f"{who} took an address from another DHCP server ({pkt['server_id']})", "warn", mac)
            else:
                self.event(f"{who} asked to keep {ip} (not ours to answer, ignored)", "info", mac)
        elif t == DECLINE:
            self.event(f"{who} declined {pkt.get('requested')} (says it's already in use)", "warn", mac)
        elif t == RELEASE:
            self.event(f"{who} released {pkt['ciaddr']}", "info", mac)

    # ------------------------------------------------------------ socket loop
    def _open(self, ip: str) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((ip, SERVER_PORT))
            sock.settimeout(1.0)
        except OSError:
            sock.close()
            raise
        return sock

    @staticmethod
    def _address_present(ip: str) -> bool:
        """True while this PC still owns `ip` (i.e. Wi-Fi/Ethernet is connected)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((ip, 0))
            return True
        except OSError:
            return False
        finally:
            s.close()

    def _run(self, cfg: dict) -> None:
        """Self-healing loop. If the PC's network drops (e.g. the modem restarts its Wi-Fi after you change
        a setting), the bound socket goes dead. We notice within seconds, wait for the address to come back
        and reopen, instead of sitting on a dead socket."""
        ip = cfg["server_ip"]
        sock, last_check, opened_at, offline_since = None, 0.0, 0.0, None
        try:
            while not self._stop.is_set():
                now = time.time()
                if sock is None:
                    if not self._address_present(ip):
                        if offline_since is None:
                            offline_since = now
                            self.event(f"This PC lost its network address {ip}. Waiting for it to reconnect…", "error")
                        self.status.update(running=False, error=f"This PC isn't connected to the network (lost {ip}). "
                                                                 "The address server resumes automatically when it's back.")
                        self._stop.wait(2)
                        continue
                    try:
                        sock = self._open(ip)
                    except OSError as e:
                        msg = str(e)
                        if getattr(e, "winerror", None) in (10048, 10013):
                            msg = ("Port 67 is already in use by another program (often Windows 'Internet Connection "
                                   "Sharing' or another DHCP server). Turn that off and HomeNet retries automatically.")
                        self.status.update(running=False, error=msg)
                        self._stop.wait(5)
                        continue
                    opened_at = last_check = now
                    if offline_since is not None:
                        self.event(f"Network is back after {round(now - offline_since)}s. Handing out addresses again.", "success")
                        offline_since = None
                    else:
                        self.event(f"Listening on {ip} (handing out {cfg['range_start']}–{cfg['range_end']})", "success")
                    self.status.update(running=True, error=None, started=self.status.get("started") or now)
                    continue

                if now - last_check >= 5:
                    last_check = now
                    stale = (now - opened_at > 300 and (self.status.get("last_packet") or 0) < now - 300)
                    if not self._address_present(ip) or stale:
                        sock.close()
                        sock = None
                        continue

                try:
                    data, _addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    continue  # Windows reports ICMP 'port unreachable' from earlier sends here; harmless
                except OSError as e:
                    log.warning("DHCP socket error, reopening: %s", e)
                    sock.close()
                    sock = None
                    continue
                pkt = parse(data)
                if not pkt:
                    continue
                self.status["last_packet"] = time.time()
                try:
                    out = self.logic.handle(pkt, stats=self.status["stats"])
                except Exception:
                    log.exception("DHCP handler error")
                    continue
                if out:
                    reply, dest = out
                    try:
                        sock.sendto(reply, (dest, CLIENT_PORT))
                    except OSError as e:
                        self.event(f"Couldn't send reply to {dest}: {e}", "error", pkt["mac"])
                try:
                    self._describe(pkt, out)
                except Exception:
                    log.exception("DHCP event log error")
        finally:
            if sock:
                sock.close()
            self.status.update(running=False)

    def other_servers(self, within: float = 3600) -> list[dict]:
        now = time.time()
        seen = self.status["stats"].get("other_servers", {})
        return [{"ip": ip, "last_seen": ts} for ip, ts in seen.items() if now - ts < within]


SERVER = DhcpServer()


# ====================================================================== active probe
def probe(timeout: float = 4.0) -> dict:
    """Broadcast a test DISCOVER (from a made-up MAC address) and list the DHCP servers that answer."""
    iface = _resolve_iface()
    mac = bytes([0x02]) + os.urandom(5)
    xid = os.urandom(4)
    pkt = bytearray(240)
    pkt[0], pkt[1], pkt[2] = 1, 1, 6
    pkt[4:8] = xid
    pkt[10:12] = b"\x80\x00"
    pkt[28:34] = mac
    pkt[236:240] = MAGIC
    data = bytes(pkt) + _opt(53, bytes([DISCOVER])) + _opt(12, b"homenet-probe") + _opt(55, bytes([1, 3, 6, 54])) + b"\xff"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    servers: dict[str, dict] = {}
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind((iface["ip"], CLIENT_PORT))
        except OSError as e:
            return {"ok": False, "error": f"Couldn't listen for replies on port 68 ({e}). Close other network tools and try again.", "servers": []}
        s.settimeout(0.5)
        s.sendto(data, ("255.255.255.255", SERVER_PORT))
        end = time.time() + timeout
        while time.time() < end:
            try:
                reply, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            r = parse(reply)
            if not r or r["op"] != 2 or r["xid"] != xid:
                continue
            sid = r.get("server_id") or addr[0]
            if sid == iface["ip"]:
                continue  # our own server
            dns = r["options"].get(6, b"")
            servers[sid] = {"ip": sid, "offered": r["yiaddr"],
                            "dns": [socket.inet_ntoa(dns[i:i + 4]) for i in range(0, len(dns) - 3, 4)]}
    finally:
        s.close()
    return {"ok": True, "servers": list(servers.values()), "checked": time.time()}


# ====================================================================== firewall
_fw_cache: dict = {"ts": 0.0, "data": None}
_PS_FW = r"""
$r = @(Get-NetFirewallRule -DisplayName 'HomeNet DHCP*' -ErrorAction SilentlyContinue | Where-Object { $_.Enabled.ToString() -eq 'True' -and $_.Direction.ToString() -eq 'Inbound' -and $_.Action.ToString() -eq 'Allow' } | ForEach-Object { [pscustomobject]@{ name = $_.DisplayName; profile = $_.Profile.ToString() } })
ConvertTo-Json -InputObject $r -Compress
"""


def firewall_status() -> dict:
    """Is there an inbound rule for UDP 67? (Created by scripts/allow-dhcp-firewall.ps1.)"""
    if _fw_cache["data"] and time.time() - _fw_cache["ts"] < 120:
        return _fw_cache["data"]
    try:
        rules = netinfo._ps(_PS_FW, timeout=30)
        data = {"ok": bool(rules), "rules": rules}
    except Exception as e:
        data = {"ok": None, "error": str(e)[:200], "rules": []}
    _fw_cache.update(ts=time.time(), data=data)
    return data


# ====================================================================== reporting
def leases() -> list[dict]:
    from . import devices as D
    now = time.time()
    devs = {d["mac"]: d for d in db.q("SELECT * FROM devices")}
    out = []
    for r in db.q("SELECT * FROM dhcp_leases ORDER BY static DESC, expires DESC"):
        d = devs.get(r["mac"])
        active = bool(r["static"]) or (r["expires"] or 0) > now
        out.append({**r, "static": bool(r["static"]), "active": active,
                    "device_id": d["id"] if d else None,
                    "device": D.display_name(d) if d else (r["hostname"] or r["mac"]),
                    "online": bool(d and d["is_online"])})
    return out
