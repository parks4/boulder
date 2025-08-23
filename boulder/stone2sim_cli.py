"""CLI to convert a STONE YAML configuration to a Python simulation script.

This command loads a Boulder STONE YAML file and generates a standalone Python
script that recreates the same Cantera simulation. The generated script is
equivalent to what would be produced by `boulder --headless --download`.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="stone2sim",
        description=(
            "Convert a STONE YAML configuration to a standalone Python simulation script. "
            "The generated script is equivalent to `boulder config.yaml --headless --download output.py`."
        ),
    )
    parser.add_argument(
        "input",
        help=(
            "Path to a STONE YAML configuration file containing reactor network definition. "
            "Must follow the Boulder STONE standard format with 'nodes', 'connections', "
            "'phases', and 'settings' sections."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Path to output Python file. Defaults to replacing .yaml with .py next to "
            "the input file."
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose progress messages"
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for stone2sim CLI.
    
    This function replicates the functionality of `boulder --headless --download`
    by using the same DualCanteraConverter to generate Python code from YAML.
    """
    args = parse_args(argv)

    if args.verbose:
        print(f"[stone2sim] Loading STONE YAML: {args.input}")

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base, _ = os.path.splitext(os.path.abspath(args.input))
        output_path = base + ".py"

    try:
        # Import Boulder's headless functionality
        from .cli import run_headless_mode
        
        if args.verbose:
            print(f"[stone2sim] Generating Python code: {output_path}")
        
        # Use the existing headless mode functionality
        run_headless_mode(args.input, output_path, args.verbose)
        
        # Always print the created file path so callers can capture/chain it
        print(f"🐍 Python simulation script created: {output_path}")
        
        if args.verbose:
            print(f"[stone2sim] Done: {output_path}")
        
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
