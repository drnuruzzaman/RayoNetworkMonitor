"""Discovers devices on the LAN.

Each scan sends one tiny UDP packet to every address in the range. That makes Windows resolve
each address with ARP, then the neighbour table tells us which MAC addresses answered. It needs
no admin rights and no extra tools.
"""
import asyncio
import ipaddress
import socket
import time

from . import alerts, db, netinfo, oui
from . import devices as D
from . import settings_store as S
from .state import STATUS

ONLINE_STATES = {"Reachable"}
NEUTRAL_STATES = {"Stale", "Delay", "Probe"}


def _probe(hosts: list[str]) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    try:
        for n, h in enumerate(hosts):
            try:
                s.sendto(b"\x00", (h, 9))
            except OSError:
                pass
            if n % 32 == 31:
                time.sleep(0.02)
    finally:
        s.close()


def _resolve(ip: str) -> str | None:
    try:
        name = socket.gethostbyaddr(ip)[0]
        return None if name == ip else name
    except OSError:
        return None


def _hosts_for(iface: dict) -> list[str]:
    subnet = S.get("scan_subnet") or "auto"
    net = ipaddress.ip_network(iface["network"] if subnet == "auto" else subnet, strict=False)
    limit = S.get("max_scan_hosts")
    out = []
    for h in net.hosts():
        if str(h) != iface["ip"]:
            out.append(str(h))
        if len(out) >= limit:
            break
    return out


def _upsert_seen(mac: str, ip: str, now: float, extra: dict | None = None) -> tuple[dict, bool]:
    """Record that a device was seen. Returns (device row, is_new)."""
    extra = extra or {}
    d = db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
    if d is None:
        vendor = oui.lookup(mac)
        db.ex("""INSERT INTO devices(mac, ip, vendor, is_private_mac, is_online, first_seen, last_seen,
                 is_self, is_gateway, type, hostname) VALUES(?,?,?,?,1,?,?,?,?,?,?)""",
              (mac, ip, vendor, int(netinfo.is_private_mac(mac)), now, now,
               int(extra.get("is_self", 0)), int(extra.get("is_gateway", 0)),
               extra.get("type") or D.guess_type(extra.get("hostname"), vendor), extra.get("hostname")))
        d = db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
        db.ex("INSERT INTO presence(device_id, start) VALUES(?, ?)", (d["id"], now))
        return d, True
    if not d["is_online"]:
        db.ex("INSERT INTO presence(device_id, start) VALUES(?, ?)", (d["id"], now))
    db.ex("""UPDATE devices SET ip=?, last_seen=?, is_online=1, missed_scans=0,
             is_self=MAX(is_self, ?), is_gateway=MAX(is_gateway, ?) WHERE id=?""",
          (ip, now, int(extra.get("is_self", 0)), int(extra.get("is_gateway", 0)), d["id"]))
    if extra.get("hostname") and not d["hostname"]:
        db.ex("UPDATE devices SET hostname=? WHERE id=?", (extra["hostname"], d["id"]))
    d = db.q1("SELECT * FROM devices WHERE id=?", (d["id"],))
    return d, False


def _set_offline(d: dict) -> None:
    db.ex("UPDATE devices SET is_online=0 WHERE id=?", (d["id"],))
    db.ex("UPDATE presence SET end=? WHERE device_id=? AND end IS NULL", (d["last_seen"], d["id"]))


async def scan_once() -> dict:
    if STATUS["scan"]["running"]:
        return {"skipped": True}
    STATUS["scan"]["running"] = True
    started = time.time()
    try:
        iface = await asyncio.to_thread(netinfo.pick_interface, S.get("scan_interface"))
        if not iface:
            raise RuntimeError("No active network adapter found. Check that this PC is connected to your home network.")
        STATUS["scan"]["interface"] = {k: iface.get(k) for k in ("alias", "ip", "prefix", "gateway", "network", "origin", "mac")}

        hosts = await asyncio.to_thread(_hosts_for, iface)
        await asyncio.to_thread(_probe, hosts)
        await asyncio.sleep(S.get("probe_wait_sec"))
        neigh = await asyncio.to_thread(netinfo.neighbours, iface["index"])

        now = time.time()
        seen_ids, neutral_macs, new_devices = set(), set(), []
        v4 = {}
        for n in neigh:
            if n["family"] == "IPv4":
                if n["state"] in ONLINE_STATES:
                    v4[n["mac"]] = n["ip"]
                elif n["state"] in NEUTRAL_STATES:
                    neutral_macs.add(n["mac"])

        # This PC isn't in its own neighbour table, so add it directly.
        if iface.get("mac"):
            d, is_new = _upsert_seen(iface["mac"], iface["ip"], now,
                                     {"is_self": 1, "type": "computer", "hostname": socket.gethostname()})
            seen_ids.add(d["id"])
        for mac, ip in v4.items():
            extra = {"is_gateway": 1, "type": "router"} if ip == iface.get("gateway") else {}
            d, is_new = _upsert_seen(mac, ip, now, extra)
            seen_ids.add(d["id"])
            if is_new:
                new_devices.append(d)

        # Remember every address (incl. IPv6) a device uses, so DNS activity maps back to it.
        mac_to_id = {r["mac"]: r["id"] for r in db.q("SELECT id, mac FROM devices")}
        for n in neigh:
            did = mac_to_id.get(n["mac"])
            if did and n["state"] in ONLINE_STATES | NEUTRAL_STATES:
                db.ex("""INSERT INTO device_ips(ip, device_id, last_seen) VALUES(?,?,?)
                         ON CONFLICT(ip) DO UPDATE SET device_id=excluded.device_id, last_seen=excluded.last_seen""",
                      (n["ip"], did, now))

        # Devices not confirmed this round.
        window = S.get("dns_online_window_min") * 60
        threshold = S.get("offline_after_missed")
        for d in db.q("SELECT * FROM devices WHERE is_online=1"):
            if d["id"] in seen_ids:
                continue
            if d["last_dns"] and now - d["last_dns"] < window:
                db.ex("UPDATE devices SET last_seen=?, missed_scans=0 WHERE id=?", (d["last_dns"], d["id"]))
                continue
            if d["mac"] in neutral_macs:
                continue
            missed = (d["missed_scans"] or 0) + 1
            db.ex("UPDATE devices SET missed_scans=? WHERE id=?", (missed, d["id"]))
            if missed >= threshold:
                _set_offline(d)

        if S.get("resolve_hostnames"):
            todo = db.q("SELECT id, ip FROM devices WHERE is_online=1 AND hostname IS NULL AND ip IS NOT NULL")
            if todo:
                names = await asyncio.gather(*[asyncio.to_thread(_resolve, r["ip"]) for r in todo])
                for r, name in zip(todo, names):
                    if name:
                        db.ex("UPDATE devices SET hostname=? WHERE id=?", (name, r["id"]))
                        row = D.get(r["id"])
                        if row and not row["type_locked"] and row["type"] == "unknown":
                            db.ex("UPDATE devices SET type=? WHERE id=?", (D.guess_type(name, row["vendor"]), r["id"]))

        if S.get("alert_new_device"):
            for d in new_devices:
                d = D.get(d["id"]) or d
                alerts.add("new_device", f"New device joined: {D.display_name(d)}",
                           f"IP {d['ip']} · MAC {d['mac']}" + (f" · {d['vendor']}" if d.get("vendor") else ""),
                           level="warning", device_id=d["id"])

        STATUS["scan"].update(last_run=now, duration=round(time.time() - started, 1),
                              found=len(seen_ids), error=None)
        return {"found": len(seen_ids), "new": len(new_devices)}
    except Exception as e:  # surfaced on the System screen
        STATUS["scan"].update(last_run=time.time(), error=str(e))
        raise
    finally:
        STATUS["scan"]["running"] = False
