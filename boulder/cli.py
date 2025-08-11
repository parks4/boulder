"""Command-line interface for Boulder.

Usage:
    boulder                  # Launches the server and opens the interface
    boulder path/to/file.yaml  # Launches with the YAML preloaded
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from .app import run_server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="boulder",
        description=(
            "Launch the Boulder server and optionally preload a YAML configuration."
        ),
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to a YAML configuration file to preload",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Port to bind (default: 8050)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the browser automatically",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # If a config path is provided, propagate it via environment for app initialization
    if args.config:
        os.environ["BOULDER_CONFIG_PATH"] = args.config

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        # Open browser slightly before server starts; browser will retry the connection
        try:
            webbrowser.open(url)
        except Exception:
            pass

    run_server(debug=args.debug, host=args.host, port=args.port)


if __name__ == "__main__":
    main(sys.argv[1:])


