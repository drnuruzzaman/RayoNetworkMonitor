from datetime import datetime, timedelta

RANGES = {"today", "yesterday", "7d", "30d"}


def local_midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def range_bounds(key: str) -> tuple[float, float, str]:
    """Return (start_epoch, end_epoch, bucket) where bucket is 'hour' or 'day'."""
    now = datetime.now().astimezone()
    today = local_midnight(now)
    if key == "yesterday":
        return (today - timedelta(days=1)).timestamp(), today.timestamp(), "hour"
    if key == "7d":
        return (today - timedelta(days=6)).timestamp(), now.timestamp(), "day"
    if key == "30d":
        return (today - timedelta(days=29)).timestamp(), now.timestamp(), "day"
    return today.timestamp(), now.timestamp(), "hour"


def buckets(lo: float, hi: float, kind: str) -> list[tuple[float, float, str]]:
    out = []
    cur = datetime.fromtimestamp(lo).astimezone()
    if kind == "day":
        cur = local_midnight(cur)
    else:
        cur = cur.replace(minute=0, second=0, microsecond=0)
    if kind == "hour":
        # Always show the whole day for hourly charts.
        end = local_midnight(cur) + timedelta(days=1)
        hi = max(hi, end.timestamp())
    while cur.timestamp() < hi:
        nxt = cur + (timedelta(days=1) if kind == "day" else timedelta(hours=1))
        label = cur.strftime("%a %d %b") if kind == "day" else cur.strftime("%H:00")
        out.append((cur.timestamp(), nxt.timestamp(), label))
        cur = nxt
    return out
