import time

from . import db


def add(type_: str, title: str, message: str = "", level: str = "info", device_id: int | None = None) -> None:
    db.ex("INSERT INTO alerts(ts, level, type, device_id, title, message) VALUES(?,?,?,?,?,?)",
          (time.time(), level, type_, device_id, title, message))


def recent_exists(type_: str, device_id: int | None, within_sec: float) -> bool:
    return bool(db.val(
        "SELECT 1 FROM alerts WHERE type=? AND IFNULL(device_id,-1)=IFNULL(?,-1) AND ts>? LIMIT 1",
        (type_, device_id, time.time() - within_sec)))
