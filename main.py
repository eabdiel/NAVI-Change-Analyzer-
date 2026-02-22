"""
NAVI-CA launcher: starts a local Bokeh server and opens the UI.
Desktop packaging target: single EXE (PyInstaller) + installer (Inno Setup).
"""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler

HERE = Path(__file__).resolve().parent

def _bkapp(doc):
    # Import lazily so packaging is simpler
    from navica.navica_app import build_document
    build_document(doc)

def main() -> int:
    port = int(os.environ.get("NAVICA_PORT", "0"))  # 0 = auto
    app = Application(FunctionHandler(_bkapp))

    server = Server({"/": app}, port=port, allow_websocket_origin=["localhost:*"])
    server.start()

    # Resolve chosen port
    actual_port = server.port
    url = f"http://localhost:{actual_port}/"

    # Open browser
    try:
        webbrowser.open(url, new=1, autoraise=True)
    except Exception:
        pass

    print(f"NAVI-CA running at {url}")
    server.io_loop.start()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
