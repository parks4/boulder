"""CLI to convert a Cantera simulation (Python script) to STONE YAML.

This command executes a Python file, searches its global variables for exactly
one ``ct.ReactorNet`` instance, and emits a STONE YAML file describing the
network topology and initial states.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

import cantera as ct  # type: ignore

from .sim2stone import write_sim_as_yaml


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sim2stone",
        description=(
            "Execute a Python file, find a single Cantera ReactorNet, and convert "
            "it to a STONE YAML file."
        ),
    )
    parser.add_argument(
        "input",
        help=(
            "Path to a Python file that builds a Cantera ct.ReactorNet. The script "
            "is executed in an isolated namespace. One and only one ReactorNet must "
            "be present among its globals."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Path to output YAML file. Defaults to replacing .py with .yaml next to "
            "the input file."
        ),
    )
    parser.add_argument(
        "--mechanism",
        default=None,
        help=(
            "Override mechanism to record in phases/gas. Defaults to internal "
            "configuration or library default."
        ),
    )
    parser.add_argument(
        "--var",
        default=None,
        help=(
            "Name of the global variable holding the ct.ReactorNet in the input script. "
            "If provided, selection is forced even if multiple networks exist."
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose progress messages"
    )
    return parser.parse_args(argv)


def _execute_and_find_network(
    script_path: str, var_name: Optional[str] = None
) -> ct.ReactorNet:
    """Execute a Python script and return the single ReactorNet it defines.

    Adds the script directory to sys.path to resolve relative imports.
    """
    import runpy

    script_abspath = os.path.abspath(script_path)
    if not os.path.isfile(script_abspath):
        raise FileNotFoundError(f"Input file does not exist: {script_path}")

    script_dir = os.path.dirname(script_abspath)
    if script_dir and script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # Execute script in its own globals namespace
    globals_dict = runpy.run_path(script_abspath, run_name="__main__")

    # If a specific variable name is provided, use it
    if var_name:
        if var_name not in globals_dict or not isinstance(
            globals_dict[var_name], ct.ReactorNet
        ):
            available = [
                k for k, v in globals_dict.items() if isinstance(v, ct.ReactorNet)
            ]
            raise RuntimeError(
                f"Variable '{var_name}' is not a ct.ReactorNet in script globals. "
                f"Available ReactorNet variables: {', '.join(available) if available else 'none'}"
            )
        return globals_dict[var_name]

    # Collect ReactorNet instances from globals
    networks = [v for v in globals_dict.values() if isinstance(v, ct.ReactorNet)]

    if len(networks) == 0:
        raise RuntimeError(
            "No ct.ReactorNet object found in script globals. Please ensure the "
            "script assigns the network to a global variable (e.g., 'sim')."
        )
    if len(networks) > 1:
        names = [k for k, v in globals_dict.items() if isinstance(v, ct.ReactorNet)]
        raise RuntimeError(
            "Multiple ct.ReactorNet objects found in script globals: "
            + ", ".join(names)
        )
    return networks[0]


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if args.verbose:
        print(f"[sim2stone] Executing: {args.input}")

    network = _execute_and_find_network(args.input, var_name=args.var)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base, _ = os.path.splitext(os.path.abspath(args.input))
        output_path = base + ".yaml"

    if args.verbose:
        print(
            f"[sim2stone] Found ReactorNet with {len(network.reactors)} reactor(s). "
            f"Writing: {output_path}"
        )

    write_sim_as_yaml(network, output_path, default_mechanism=args.mechanism)

    if args.verbose:
        print(f"[sim2stone] Done: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
