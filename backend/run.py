"""Starts HomeNet Monitor. The listen address and port come from Settings (stored in the database),
so changing them in the UI and pressing 'Restart' takes effect without editing any file."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

from app import db  # noqa: E402
from app import settings_store as S  # noqa: E402


def main():
    db.init()
    while True:
        host, port = S.get("ui_bind_host"), S.get("ui_port")
        from app.main import app

        app.state.restart = False
        config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
        server = uvicorn.Server(config)
        app.state.server = server
        print(f"\n  HomeNet Monitor → http://localhost:{port}\n", flush=True)
        server.run()
        if not app.state.restart:
            break
        print("  Restarting with new settings…", flush=True)


if __name__ == "__main__":
    main()
