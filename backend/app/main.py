import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, detect, dhcp, psl, tasks, usage
from .api import api, public
from .config import FRONTEND_DIST, VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()

    def quiet_disconnects(loop, ctx):
        # Windows' Proactor loop logs a scary traceback whenever a browser drops a connection.
        if isinstance(ctx.get("exception"), OSError) and "_call_connection_lost" in str(ctx.get("handle", "")):
            return
        loop.default_exception_handler(ctx)

    loop.set_exception_handler(quiet_disconnects)
    db.init()
    psl.load_from_disk()
    usage.seed_services()
    detect.redo_if_rules_changed()
    running = tasks.start()
    yield
    for t in running:
        t.cancel()
    dhcp.SERVER.stop()


app = FastAPI(title="HomeNet Monitor", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(public)
app.include_router(api)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    f = FRONTEND_DIST / path
    if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
        return FileResponse(f)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "The web UI hasn't been built yet. Run start.ps1."}, status_code=503)
