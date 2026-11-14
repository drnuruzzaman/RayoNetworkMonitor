"""SQLite access helpers. One connection per thread, WAL mode, autocommit unless inside `transaction()`."""
import contextlib
import json
import sqlite3
import threading

from .config import DATA_DIR, DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS devices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    mac            TEXT UNIQUE NOT NULL,
    ip             TEXT,
    hostname       TEXT,
    name           TEXT,
    owner          TEXT,
    type           TEXT DEFAULT 'unknown',
    type_locked    INTEGER DEFAULT 0,
    vendor         TEXT,
    notes          TEXT,
    is_private_mac INTEGER DEFAULT 0,
    is_online      INTEGER DEFAULT 0,
    is_self        INTEGER DEFAULT 0,
    is_gateway     INTEGER DEFAULT 0,
    trusted        INTEGER DEFAULT 0,
    first_seen     REAL,
    last_seen      REAL,
    last_dns       REAL,
    missed_scans   INTEGER DEFAULT 0,
    paused         INTEGER DEFAULT 0,
    paused_until   REAL,
    controls       TEXT,
    ag_client_name TEXT,
    ag_applied     TEXT
);

CREATE TABLE IF NOT EXISTS device_ips (
    ip        TEXT PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    last_seen REAL
);

CREATE TABLE IF NOT EXISTS presence (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    start     REAL NOT NULL,
    end       REAL
);
CREATE INDEX IF NOT EXISTS ix_presence_dev ON presence(device_id, start);

CREATE TABLE IF NOT EXISTS services (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    category   TEXT NOT NULL,
    domains    TEXT NOT NULL,
    track_time INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dns_queries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    client     TEXT,
    device_id  INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    domain     TEXT,
    qtype      TEXT,
    blocked    INTEGER DEFAULT 0,
    reason     TEXT,
    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_dns_ts ON dns_queries(ts);
CREATE INDEX IF NOT EXISTS ix_dns_dev ON dns_queries(device_id, ts);

CREATE TABLE IF NOT EXISTS usage_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    start      REAL NOT NULL,
    end        REAL NOT NULL,
    queries    INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_usage_dev ON usage_sessions(device_id, end);
CREATE INDEX IF NOT EXISTS ix_usage_end ON usage_sessions(end);

CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    device_ids TEXT NOT NULL,
    action     TEXT NOT NULL,
    services   TEXT,
    days       TEXT NOT NULL,
    start      TEXT NOT NULL,
    end        TEXT NOT NULL,
    enabled    INTEGER DEFAULT 1,
    created    REAL
);

CREATE TABLE IF NOT EXISTS alerts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    level     TEXT DEFAULT 'info',
    type      TEXT,
    device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    title     TEXT,
    message   TEXT,
    read      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_alerts_ts ON alerts(ts);

CREATE TABLE IF NOT EXISTS dhcp_leases (
    mac      TEXT PRIMARY KEY,
    ip       TEXT NOT NULL,
    hostname TEXT,
    expires  REAL,
    static   INTEGER DEFAULT 0,
    updated  REAL
);
CREATE INDEX IF NOT EXISTS ix_dhcp_ip ON dhcp_leases(ip);

CREATE TABLE IF NOT EXISTS oui (
    prefix TEXT PRIMARY KEY,
    vendor TEXT
);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        _local.c = c
    return c


def init():
    conn().executescript(SCHEMA)


def q(sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def q1(sql: str, params=()) -> dict | None:
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def val(sql: str, params=()):
    r = conn().execute(sql, params).fetchone()
    return r[0] if r else None


def ex(sql: str, params=()) -> sqlite3.Cursor:
    return conn().execute(sql, params)


def exmany(sql: str, rows) -> None:
    conn().executemany(sql, rows)


@contextlib.contextmanager
def transaction():
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def jload(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default
