"""Entrypoint for the local frontend-driven video generation app."""

from __future__ import annotations

import argparse
import sys

from config.settings import get_settings
from modules.web_app import launch_web_app


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the local web app."""
    parser = argparse.ArgumentParser(
        description="Launch the AI Stack Automation frontend and generation server.",
    )
    parser.add_argument(
        "--host",
        help="Optional override for the local web server host.",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Optional override for the local web server port.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening the browser automatically.",
    )
    return parser.parse_args()


def main() -> int:
    """Launch the local web app."""
    settings = get_settings()
    args = parse_args()

    if args.host:
        object.__setattr__(settings, "frontend_host", args.host)
    if args.port:
        object.__setattr__(settings, "frontend_port", args.port)

    launch_web_app(settings=settings, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
