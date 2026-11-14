"""HomeNet launcher logic (no window code here, so it can be tested on its own).

Starts/stops the HomeNet server in the background, reports whether it's running, opens the dashboard,
and turns "start with Windows" on or off via a shortcut in the user's Startup folder (no admin needed).
"""
import ctypes
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VENV = ROOT / ".venv" / "Scripts"
PYTHONW = VENV / "pythonw.exe"
PYTHON = VENV / "python.exe"
DATA = pathlib.Path(os.environ.get("HNM_DATA_DIR", ROOT / "data"))
LOG = DATA / "homenet.log"
LAUNCHER = ROOT / "HomeNet.pyw"
SHORTCUT_NAME = "HomeNet Monitor.lnk"

NO_WINDOW = 0x08000000
DETACHED = 0x00000008
NEW_GROUP = 0x00000200
BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB


# ------------------------------------------------------------------ settings (read from HomeNet's own database)
def server_address() -> tuple[str, int]:
    """(host, port) from HomeNet's settings, so the launcher never hard-codes them."""
    sys.path.insert(0, str(BACKEND))
    try:
        from app import db, settings_store as S  # noqa: E402
        db.init()
        return S.get("ui_bind_host"), int(S.get("ui_port"))
    except Exception:
        return "0.0.0.0", 8090


def dashboard_url() -> str:
    return f"http://localhost:{server_address()[1]}"


# ------------------------------------------------------------------ status
def is_running(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{dashboard_url()}/api/setup/status", timeout=timeout) as r:
            return r.status == 200 and "version" in json.loads(r.read().decode())
    except Exception:
        return False


def listening_pid(port: int) -> int | None:
    """PID of the process listening on the port (via netstat; works without admin)."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=10).stdout
    except Exception:
        return None
    for line in out.splitlines():
        m = re.match(rf"\s*TCP\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def process_name(pid: int) -> str:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, creationflags=NO_WINDOW, timeout=10).stdout.strip()
        return out.split(",")[0].strip('"').lower() if out else ""
    except Exception:
        return ""


# ------------------------------------------------------------------ start / stop
def ready() -> str | None:
    """None if HomeNet can be started, otherwise a message saying what's missing."""
    if not PYTHONW.exists():
        return "The Python environment is missing. Run start.ps1 once first."
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        return "The web UI hasn't been built yet. Run start.ps1 once first."
    return None


def start() -> str:
    if is_running():
        return "HomeNet is already running."
    problem = ready()
    if problem:
        raise RuntimeError(problem)
    DATA.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 5 * 1024 * 1024:
        LOG.replace(LOG.with_suffix(".log.1"))
    log = open(LOG, "a", encoding="utf-8")
    log.write(f"\n===== HomeNet started by launcher {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    log.flush()
    cmd = [str(PYTHONW), str(BACKEND / "run.py")]
    kw = dict(cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, close_fds=True)
    try:
        # Break away from any Windows "job" the launcher runs in, so closing the launcher (or the terminal/IDE
        # that opened it) can't take HomeNet down with it.
        subprocess.Popen(cmd, creationflags=DETACHED | NEW_GROUP | NO_WINDOW | BREAKAWAY, **kw)
    except OSError:
        subprocess.Popen(cmd, creationflags=DETACHED | NEW_GROUP | NO_WINDOW, **kw)
    for _ in range(60):
        time.sleep(0.5)
        if is_running():
            return "HomeNet started."
    raise RuntimeError(f"HomeNet didn't start within 30 seconds. See the log: {LOG}")


def stop() -> str:
    port = server_address()[1]
    pid = listening_pid(port)
    if not pid:
        return "HomeNet isn't running."
    name = process_name(pid)
    if name and "python" not in name:
        raise RuntimeError(f"Port {port} is used by '{name}', not HomeNet. Not stopping it.")
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW, timeout=15)
    for _ in range(20):
        time.sleep(0.25)
        if not listening_pid(port):
            return "HomeNet stopped."
    raise RuntimeError("HomeNet didn't stop. Try again, or restart Windows.")


def restart() -> str:
    stop()
    return start()


def open_dashboard() -> None:
    webbrowser.open(dashboard_url())


def adguard_url() -> str:
    """AdGuard Home's admin address, as saved in HomeNet's Settings → AdGuard Home."""
    sys.path.insert(0, str(BACKEND))
    try:
        from app import db, settings_store as S  # noqa: E402
        db.init()
        return (S.get("adguard_url") or "").rstrip("/")
    except Exception:
        return ""


ADGUARD_SERVICE = "AdGuardHome"   # Windows service created by scripts/install-adguard.ps1


def adguard_service_state() -> str:
    """'running', 'stopped', 'starting', 'stopping' or 'not installed'. Reading status needs no admin."""
    try:
        out = subprocess.run(["sc.exe", "query", ADGUARD_SERVICE], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=10).stdout
    except Exception:
        return "unknown"
    m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", out)
    if not m:
        return "not installed"
    return {"RUNNING": "running", "STOPPED": "stopped", "START_PENDING": "starting",
            "STOP_PENDING": "stopping"}.get(m.group(1), m.group(1).lower())


def adguard_service(action: str) -> str:
    """Start / stop / restart the AdGuard Home service. Windows asks for admin permission (UAC)."""
    cmd = {"start": "Start-Service", "stop": "Stop-Service", "restart": "Restart-Service"}[action]
    if adguard_service_state() == "not installed":
        raise RuntimeError("AdGuard Home isn't installed as a service. Run scripts\\install-adguard.ps1 first.")
    # Start-Service has no -Force switch (only Stop/Restart do), so add it only where it's valid.
    force = " -Force" if action in ("stop", "restart") else ""
    inner = f"try {{ {cmd} -Name {ADGUARD_SERVICE}{force} -ErrorAction Stop; exit 0 }} catch {{ exit 1 }}"
    # Run elevated (UAC prompt), wait, and pass the elevated command's exit code back to us.
    ps = ("$p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
          f"-ArgumentList '-NoProfile','-NonInteractive','-Command','{inner}'; exit $p.ExitCode")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                       creationflags=NO_WINDOW, timeout=120)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        if "canceled by the user" in msg.lower() or "cancelled" in msg.lower():
            raise RuntimeError("Cancelled. Windows needs admin permission to control AdGuard Home.")
        if not msg:
            msg = (f"Windows couldn't {action} the service. Open Services (services.msc), find 'AdGuardHome' "
                   f"and check it there, or look in C:\\AdGuardHome for errors.")
        raise RuntimeError(f"Couldn't {action} AdGuard Home: {msg[:300]}")
    want = "stopped" if action == "stop" else "running"
    for _ in range(40):
        if adguard_service_state() == want:
            return f"AdGuard Home {'stopped' if action == 'stop' else 'is running'}."
        time.sleep(0.5)
    raise RuntimeError(f"AdGuard Home is still '{adguard_service_state()}'. Check Windows Services.")


def adguard_web_ok(timeout: float = 1.5) -> bool:
    """Is AdGuard's admin page answering? (A login challenge still counts as up.)"""
    url = adguard_url()
    if not url:
        return False
    try:
        with urllib.request.urlopen(f"{url}/control/status", timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def open_adguard() -> None:
    url = adguard_url()
    if not url:
        raise RuntimeError("AdGuard Home's address isn't set yet. Add it in HomeNet → Settings → AdGuard Home.")
    webbrowser.open(url)


# ------------------------------------------------------------------ Windows folders & shortcuts
def _known_folder(csidl: int) -> pathlib.Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return pathlib.Path(buf.value)


def startup_folder() -> pathlib.Path:
    return _known_folder(0x0007)  # CSIDL_STARTUP


def desktop_folder() -> pathlib.Path:
    return _known_folder(0x0010)  # CSIDL_DESKTOPDIRECTORY


def _make_shortcut(path: pathlib.Path, args: str, description: str) -> None:
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:HN_LNK); "
        "$s.TargetPath = $env:HN_TARGET; $s.Arguments = $env:HN_ARGS; $s.WorkingDirectory = $env:HN_DIR; "
        "$s.Description = $env:HN_DESC; $s.IconLocation = $env:HN_ICON; $s.Save()"
    )
    env = dict(os.environ, HN_LNK=str(path), HN_TARGET=str(PYTHONW), HN_ARGS=f'"{LAUNCHER}" {args}'.strip(),
               HN_DIR=str(ROOT), HN_DESC=description, HN_ICON="%SystemRoot%\\System32\\imageres.dll,186")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30)
    if r.returncode != 0 or not path.exists():
        raise RuntimeError(f"Couldn't create the shortcut: {(r.stderr or r.stdout).strip()[:300]}")


def startup_enabled() -> bool:
    return (startup_folder() / SHORTCUT_NAME).exists()


def set_startup(enabled: bool) -> None:
    lnk = startup_folder() / SHORTCUT_NAME
    if enabled:
        _make_shortcut(lnk, "--autostart --minimized", "Start HomeNet Monitor when Windows starts")
    elif lnk.exists():
        lnk.unlink()


def create_desktop_shortcut() -> pathlib.Path:
    lnk = desktop_folder() / SHORTCUT_NAME
    _make_shortcut(lnk, "", "HomeNet Monitor launcher")
    return lnk


def open_log() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    LOG.touch(exist_ok=True)
    os.startfile(str(LOG))  # noqa: S606 - opens in the user's default text editor
