"""Command-line interface for Boulder.

Usage:
    boulder                  # Launches the server and opens the interface
    boulder path/to/file.yaml  # Launches with the YAML preloaded
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import webbrowser


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def find_available_port(host: str, start_port: int, max_attempts: int = 10) -> int:
    """Find the next available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(host, port):
            return port
    raise RuntimeError(
        f"Could not find an available port in range {start_port}-{start_port + max_attempts - 1}"
    )


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
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output in server console",
    )
    parser.add_argument(
        "--no-port-search",
        action="store_true",
        help="Do not search for alternative ports if the specified port is in use",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # If a config path is provided, propagate it via environment for app initialization
    if args.config:
        os.environ["BOULDER_CONFIG_PATH"] = args.config

    # Set verbose mode via environment variable for app initialization
    if args.verbose:
        os.environ["BOULDER_VERBOSE"] = "1"

    # Check if the requested port is available, find alternative if not
    original_port = args.port
    if is_port_in_use(args.host, args.port):
        if args.no_port_search:
            print(f"Error: Port {args.port} is already in use.")
            print(
                f"Please specify a different port using --port or stop the service using port {args.port}"
            )
            print(
                "Alternatively, remove --no-port-search to automatically find an available port."
            )
            sys.exit(1)
        else:
            try:
                available_port = find_available_port(args.host, args.port)
                print(
                    f"Port {args.port} is already in use. Using port {available_port} instead."
                )
                args.port = available_port
            except RuntimeError as e:
                print(f"Error: {e}")
                print(
                    f"Please specify a different port using --port or stop the service using port {args.port}"
                )
                sys.exit(1)
    elif args.verbose:
        print(f"Port {args.port} is available.")

    # Import cantera_converter early to ensure plugins are loaded at app startup
    from . import cantera_converter  # noqa: F401

    # Import after environment is set so app initialization can read it
    from .app import run_server

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        # Open browser slightly before server starts; browser will retry the connection
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if args.verbose and args.port != original_port:
        print(f"Boulder server will start on {url} (port changed from {original_port})")
    elif args.verbose:
        print(f"Boulder server will start on {url}")

    run_server(debug=args.debug, host=args.host, port=args.port, verbose=args.verbose)


if __name__ == "__main__":
    main(sys.argv[1:])
