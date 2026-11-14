"""Manufacturer lookup from the IEEE OUI list, downloaded on request from the Settings screen."""
import csv
import io
import time

import httpx

from . import db
from . import settings_store as S


def lookup(mac: str | None) -> str | None:
    if not mac:
        return None
    prefix = mac.replace(":", "")[:6].upper()
    row = db.q1("SELECT vendor FROM oui WHERE prefix=?", (prefix,))
    return row["vendor"] if row else None


def count() -> int:
    return db.val("SELECT COUNT(*) FROM oui") or 0


async def update_from_url() -> int:
    url = S.get("oui_url")
    async with httpx.AsyncClient(timeout=120, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (HomeNet Monitor)"}) as c:
        r = await c.get(url)
        r.raise_for_status()
        text = r.text
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 3 or rec[0] == "Registry":
            continue
        prefix = rec[1].strip().upper()
        if len(prefix) == 6:
            rows.append((prefix, rec[2].strip()))
    if not rows:
        raise ValueError("The file didn't contain any manufacturer entries")
    with db.transaction() as c:
        c.execute("DELETE FROM oui")
        c.executemany("INSERT OR REPLACE INTO oui(prefix, vendor) VALUES(?, ?)", rows)
    S.set("oui_updated", time.time())
    # Back-fill vendors on known devices.
    for d in db.q("SELECT id, mac FROM devices"):
        v = lookup(d["mac"])
        if v:
            db.ex("UPDATE devices SET vendor=? WHERE id=?", (v, d["id"]))
    return len(rows)
