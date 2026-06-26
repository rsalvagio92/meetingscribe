"""Entry point. Starts the local server; opens a desktop window if pywebview is
installed, otherwise prints the URL for a browser.

  meetingscribe              # desktop window (or browser if --no-window)
  meetingscribe --no-window  # headless server only
  meetingscribe --port 8000
"""
from __future__ import annotations

import argparse
import threading
import time

import uvicorn

from .api.server import AppState, create_app


def _run_server(app, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(prog="meetingscribe")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--no-window", action="store_true", help="server only, no desktop window")
    args = parser.parse_args()

    state = AppState()
    app = create_app(state)
    url = f"http://{args.host}:{args.port}"

    if args.no_window:
        _run_server(app, args.host, args.port)
        return

    try:
        import webview  # type: ignore
    except ImportError:
        print(f"pywebview not installed; open {url} in your browser.")
        print("Install the desktop window with: pip install 'meetingscribe[desktop]'")
        _run_server(app, args.host, args.port)
        return

    server = threading.Thread(
        target=_run_server, args=(app, args.host, args.port), daemon=True
    )
    server.start()
    time.sleep(1.0)  # let uvicorn bind before the window loads
    webview.create_window("MeetingScribe", url, width=1100, height=780)
    webview.start()


if __name__ == "__main__":
    main()
