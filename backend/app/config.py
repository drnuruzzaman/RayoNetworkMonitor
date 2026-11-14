"""Bootstrap paths only. Every runtime setting lives in the database and is edited from the web UI."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = pathlib.Path(os.environ.get("HNM_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "homenet.db"
FRONTEND_DIST = ROOT / "frontend" / "dist"
VERSION = "1.0.0"
