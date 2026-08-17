"""Start the local Valuation dashboard and open it in a browser."""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

import app


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the local financial report dashboard."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind to. Default: {DEFAULT_HOST}",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind to. Default: {DEFAULT_PORT}",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser window.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)

    os.environ["VALUATION_DASHBOARD_HOST"] = args.host
    os.environ["VALUATION_DASHBOARD_PORT"] = str(args.port)

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    print("Starting Financial Report Dashboard...")
    print(f"URL: {url}")
    print("Press Ctrl+C to stop.")
    return app.main()


if __name__ == "__main__":
    raise SystemExit(main())
