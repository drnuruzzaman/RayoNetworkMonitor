import os, json, time, hashlib, sqlite3, threading, logging
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import csv, io

load_dotenv()
AGH_URL = os.getenv("AGH_URL", "http://127.0.0.1:3000").rstrip("/")
AGH_USER = os.getenv("AGH_USERNAME", "")
AGH_PASS = os.getenv("AGH_PASSWORD", "")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "20"))
DB_PATH = Path(os.getenv("DB_PATH", "data/monitor.db"))
DEVICE_MAP_PATH = Path(os.getenv("DEVICE_MAP_PATH", "devices.json"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("home-net-monitor")
app = FastAPI(title="Home Network Monitor", version="0.1.0")
stop_event = threading.Event()
worker = None

# Lightweight, editable domain classification. This is categorisation, not proof
# of the exact app/page viewed. Add/remove domains to suit your household.
DOMAIN_GROUPS = {
    "Social": ["instagram.com", "tiktok.com", "snapchat.com", "facebook.com", "discord.com", "reddit.com", "x.com"],
    "Video & streaming": ["youtube.com", "youtu.be", "netflix.com", "twitch.tv", "disneyplus.com", "primevideo.com"],
    "Gaming": ["roblox.com", "epicgames.com", "steampowered.com", "playstation.com", "xbox.com"],
    "Search": ["google.com", "bing.com", "duckduckgo.com"],
    "Messaging": ["whatsapp.com", "telegram.org", "messenger.com", "signal.org"],
}
BLOCK_REASONS = {
    "FilteredBlackList", "FilteredSafeBrowsing", "FilteredParental",
    "FilteredInvalid", "FilteredSafeSearch",
}

def category_for(domain):
    d = (domain or "").lower().rstrip(".")
    for group, roots in DOMAIN_GROUPS.items():
        if any(d == root or d.endswith("." + root) for root in roots):
            return group
    return "Other"

def device_map():
    try:
        return json.loads(DEVICE_MAP_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS events (
          event_id TEXT PRIMARY KEY,
          event_time TEXT NOT NULL,
          client_ip TEXT,
          device_name TEXT,
          owner TEXT,
          domain TEXT,
          query_type TEXT,
          reason TEXT,
          blocked INTEGER NOT NULL,
          category TEXT NOT NULL,
          raw_json TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events(event_time)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_device ON events(client_ip)")

def parse_time(value):
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()

def fetch_querylog():
    auth = HTTPBasicAuth(AGH_USER, AGH_PASS) if AGH_USER else None
    r = requests.get(f"{AGH_URL}/control/querylog",
                     params={"limit": 500}, auth=auth, timeout=12)
    r.raise_for_status()
    payload = r.json()
    return payload.get("data", []) if isinstance(payload, dict) else payload

def store_events(items):
    mapping = device_map()
    inserted = 0
    with db() as c:
        for item in items:
            question = item.get("question") or {}
            domain = (question.get("host") or "").lower().rstrip(".")
            client_ip = item.get("client") or ""
            info = mapping.get(client_ip, {})
            reason = item.get("reason") or ""
            # AdGuard Home reason values indicate whether a filter matched.
            blocked = int(reason in BLOCK_REASONS)
            event_time = parse_time(item.get("time"))
            raw = json.dumps(item, separators=(",", ":"), ensure_ascii=False)
            event_id = hashlib.sha256(
                (event_time + "|" + client_ip + "|" + domain + "|" +
                 str(question.get("type", "")) + "|" + reason).encode()
            ).hexdigest()
            cur = c.execute("""
              INSERT OR IGNORE INTO events
              (event_id,event_time,client_ip,device_name,owner,domain,query_type,
               reason,blocked,category,raw_json)
              VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (event_id,event_time,client_ip,info.get("name", "Unidentified device"),
                  info.get("owner", "Unassigned"),domain,question.get("type",""),
                  reason,blocked,category_for(domain),raw))
            inserted += cur.rowcount
    return inserted

def collector():
    log.info("Collector started: %s", AGH_URL)
    while not stop_event.is_set():
        try:
            n = store_events(fetch_querylog())
            if n:
                log.info("Stored %s new DNS events", n)
        except Exception as e:
            log.warning("Collector error: %s", e)
        stop_event.wait(POLL_SECONDS)

@app.on_event("startup")
def startup():
    global worker
    init_db()
    stop_event.clear()
    worker = threading.Thread(target=collector, daemon=True)
    worker.start()

@app.on_event("shutdown")
def shutdown():
    stop_event.set()
    if worker:
        worker.join(timeout=3)

@app.get("/health")
def health():
    with db() as c:
        count = c.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
    return {"status":"ok","events_stored":count,"adguard_url":AGH_URL}

@app.get("/api/devices")
def devices():
    with db() as c:
        rows = c.execute("""
          SELECT client_ip, COALESCE(MAX(device_name),'Unidentified device') device_name,
                 COALESCE(MAX(owner),'Unassigned') owner, COUNT(*) dns_queries,
                 SUM(blocked) blocked_queries, MAX(event_time) last_seen
          FROM events GROUP BY client_ip ORDER BY dns_queries DESC
        """).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/events")
def events(limit: int = 200, device_ip: str | None = None):
    limit = max(1, min(limit, 2000))
    with db() as c:
        if device_ip:
            rows = c.execute("SELECT * FROM events WHERE client_ip=? ORDER BY event_time DESC LIMIT ?",
                             (device_ip,limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM events ORDER BY event_time DESC LIMIT ?",
                             (limit,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/report.csv")
def report_csv(days: int = 7):
    days = max(1, min(days, 90))
    cutoff = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    with db() as c:
        rows = c.execute("""
          SELECT event_time,device_name,owner,client_ip,domain,category,blocked,reason
          FROM events WHERE event_time >= ? ORDER BY event_time DESC
        """,(cutoff,)).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["event_time","device","owner","client_ip","domain","category","blocked","reason"])
    writer.writerows([tuple(r) for r in rows])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=home-network-{days}d.csv"})

@app.delete("/api/old-events")
def delete_old_events(days: int = 30):
    days = max(1, min(days, 365))
    cutoff = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    with db() as c:
        cur = c.execute("DELETE FROM events WHERE event_time < ?", (cutoff,))
    return {"deleted":cur.rowcount,"retention_days":days}
