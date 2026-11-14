"""Is a person actually using the device?

A locked phone or tablet keeps talking to the internet: iCloud sync, app refresh, push keep-alives,
CDN fetches. That traffic is small and *repetitive*: the same few background hosts over and over.
When someone is actually using the device, it reaches lots of different user-facing hosts
(video segments, feeds, images, pages).

So we look at each device in short windows (default 5 minutes) and count the distinct
*foreground* hosts it contacted, ignoring:
  * lookups AdGuard blocked (trackers, ads)
  * apps marked as background / not screen time / System category
  * cloud & CDN infrastructure (cloudfront.net, akamai, googleapis, …)
A window with at least N foreground hosts (default 3) counts as "in use". Short gaps between
in-use windows are bridged so reading an article or watching a video isn't chopped up.

Measured on this network: locked iPad = 0-2 foreground hosts per 5 min, phone in use = 8-28.
"""
import threading
import time

from . import db, detect, psl
from . import settings_store as S

_cache: dict = {}
_lock = threading.Lock()
_site_cache: dict[str, bool] = {}


# Devices nobody "uses" like a screen: their traffic is never screen time.
NON_HUMAN_TYPES = {"router", "iot", "printer", "camera", "speaker"}


def non_human_device_ids() -> set[int]:
    marks = ",".join("?" * len(NON_HUMAN_TYPES))
    return {r["id"] for r in db.q(f"SELECT id FROM devices WHERE is_gateway=1 OR type IN ({marks})", tuple(NON_HUMAN_TYPES))}


def _background_service_ids() -> set[int]:
    return {r["id"] for r in db.q("SELECT id FROM services WHERE track_time=0 OR hidden=1 OR category='System'")}


def _is_infra(domain: str) -> bool:
    v = _site_cache.get(domain)
    if v is None:
        site = psl.registrable(domain) or domain
        v = detect.is_infrastructure(site)
        if len(_site_cache) > 50000:
            _site_cache.clear()
        _site_cache[domain] = v
    return v


def _params() -> tuple[int, int, int]:
    return (S.get("activity_window_min") * 60, S.get("activity_min_hosts"), S.get("activity_bridge_min") * 60)


def _foreground_hosts(lo: float, hi: float, device_id: int | None, bucket: int) -> dict[tuple[int, int], set]:
    bg = _background_service_ids()
    sql = "SELECT device_id, ts, domain, blocked, service_id FROM dns_queries WHERE ts>=? AND ts<? AND device_id IS NOT NULL"
    params: list = [lo, hi]
    if device_id:
        sql += " AND device_id=?"
        params.append(device_id)
    out: dict[tuple[int, int], set] = {}
    skip = non_human_device_ids()
    for r in db.q(sql, params):
        if r["device_id"] in skip or r["blocked"] or (r["service_id"] in bg) or not r["domain"] or _is_infra(r["domain"]):
            continue
        out.setdefault((r["device_id"], int(r["ts"] // bucket)), set()).add(r["domain"])
    return out


def active_intervals(lo: float, hi: float, device_id: int | None = None) -> dict[int, list[tuple[float, float]]]:
    """device_id → merged [(start, end)] periods when a person was using the device, clipped to [lo, hi]."""
    if not S.get("activity_detection"):
        return {}
    bucket, min_hosts, bridge = _params()
    key = (int(lo // 60), int(hi // 60), device_id, bucket, min_hosts, bridge)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
    hosts = _foreground_hosts(lo - bucket, hi, device_id, bucket)
    per_dev: dict[int, list[int]] = {}
    for (did, b), hs in hosts.items():
        if len(hs) >= min_hosts:
            per_dev.setdefault(did, []).append(b)
    result: dict[int, list[tuple[float, float]]] = {}
    for did, bs in per_dev.items():
        spans: list[list[float]] = []
        for b in sorted(bs):
            s, e = b * bucket, (b + 1) * bucket
            if spans and s - spans[-1][1] <= bridge:
                spans[-1][1] = e
            else:
                spans.append([s, e])
        clipped = [(max(s, lo), min(e, hi)) for s, e in spans if e > lo and s < hi]
        if clipped:
            result[did] = clipped
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.time(), result)
    return result


def overlap(start: float, end: float, intervals: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(end, e) - max(start, s)) for s, e in intervals)


def total(intervals: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in intervals)


def in_use_now(now: float | None = None) -> dict[int, bool]:
    """device_id → True if it reached enough foreground hosts in the last window."""
    if not S.get("activity_detection"):
        return {}
    now = now or time.time()
    bucket, min_hosts, _ = _params()
    hosts: dict[int, set] = {}
    bg = _background_service_ids()
    skip = non_human_device_ids()
    for r in db.q("SELECT device_id, domain, blocked, service_id FROM dns_queries WHERE ts>=? AND device_id IS NOT NULL",
                  (now - bucket,)):
        if r["device_id"] in skip or r["blocked"] or r["service_id"] in bg or not r["domain"] or _is_infra(r["domain"]):
            continue
        hosts.setdefault(r["device_id"], set()).add(r["domain"])
    return {did: len(h) >= min_hosts for did, h in hosts.items()}
