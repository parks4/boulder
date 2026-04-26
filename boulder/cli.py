"""Command-line interface for Boulder.

Usage:
    boulder                  # Launches the server and opens the interface
    boulder path/to/file.yaml  # Launches with the YAML preloaded
    boulder --dev            # Launches in development mode with Vite dev server
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import webbrowser
from pathlib import Path

# Load .env from the repository root so that BOULDER_PLUGINS and other
# settings are available for both headless and GUI modes.
try:
    from dotenv import load_dotenv  # type: ignore

    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.is_file():
        load_dotenv(dotenv_path=_env_file, override=False)
except ImportError:
    pass


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
    dev_epilog = (
        "Developers:\n"
        "  If you changed the frontend and need a production rebuild, run:\n"
        "  cd frontend && npm install && npm run build"
    )
    parser = argparse.ArgumentParser(
        prog="boulder",
        description=(
            "Launch the Boulder server and optionally preload a YAML configuration."
        ),
        epilog=dev_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to a configuration file to preload (.yaml, .yml, or .py)",
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
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without starting the web UI",
    )
    parser.add_argument(
        "--download",
        metavar="OUTPUT_FILE",
        help="Generate Python code from YAML and save to file (requires --headless)",
    )
    parser.add_argument(
        "--output-yaml",
        metavar="YAML_FILE",
        help=(
            "Output path for generated STONE YAML when converting a .py file "
            "with --headless (default: replaces .py with _stone.yaml next to input)"
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run the development frontend (starts both backend and Vite dev server)",
    )
    parser.add_argument(
        "--runner",
        metavar="PKG.MOD:CLASS",
        default=None,
        help=(
            "Dotted-path to a BoulderRunner subclass to use (e.g. "
            "'bloc.runner:BlocRunner').  Primarily used by the `bloc` CLI."
        ),
    )
    return parser.parse_args(argv)


def run_headless_mode(
    config_path: str, output_path: str, verbose: bool = False
) -> None:
    """Run Boulder in headless mode to generate Python code from YAML configuration.

    This function provides a command-line interface for generating standalone Python
    scripts from Boulder YAML configurations without launching the web UI. The generated
    Python code contains a complete Cantera simulation that can be executed independently.

    CLI Usage Examples:
    ------------------

    Basic usage:
        boulder config.yaml --headless --download output.py

    With verbose output:
        boulder config.yaml --headless --download output.py --verbose

    Using relative paths:
        boulder configs/mix_react_streams.yaml --headless --download simulation.py

    Using absolute paths:
        boulder C:/path/to/config.yaml --headless --download C:/output/simulation.py

    Parameters
    ----------
    config_path : str
        Path to the YAML configuration file containing the reactor network definition.
        Must follow the Boulder STONE standard format with 'nodes', 'connections',
        'phases', and 'settings' sections.

    output_path : str
        Path where the generated Python script will be saved. The script will contain
        all necessary imports, reactor setup, network configuration, and simulation loop.

    verbose : bool, optional
        If True, prints detailed progress information during code generation including
        configuration loading, network building, and simulation execution steps.
        Default is False.

    Generated Python Code Features:
    ------------------------------
    - Complete Cantera imports and mechanism loading
    - Reactor creation with proper initial conditions
    - Mass flow controllers and connection setup
    - Network configuration with solver tolerances
    - Simulation loop with time advancement
    - Temperature and state output during simulation
    - Inline comments explaining each step

    Raises
    ------
    FileNotFoundError
        If the specified config_path does not exist
    ValueError
        If the YAML configuration is invalid or contains unsupported reactor types
    RuntimeError
        If network building or simulation fails due to numerical issues

    Notes
    -----
    The generated Python script is completely standalone and can be executed with:
        python output.py

    The script will run the simulation and print time-series data to the console.
    For advanced post-processing, users can modify the generated script to save
    data to files or create custom plots.

    Examples
    --------
    .. minigallery:: boulder.cli.run_headless_mode
       :add-heading: Examples using headless conversion
    """
    try:
        # Load and validate config (supports .py, .yaml, .yml)
        from .config import (
            load_config_file_with_py_support,
            normalize_config,
            validate_config,
        )

        if verbose:
            print(f"Loading configuration from: {config_path}")

        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        config, actual_yaml_path = load_config_file_with_py_support(
            config_path, verbose
        )
        normalized_config = normalize_config(config)
        validated_config = validate_config(normalized_config)

        if verbose:
            num_nodes = len(validated_config.get("nodes", []))
            num_conns = len(validated_config.get("connections", []))
            print(f"Loaded configuration: {num_nodes} nodes, {num_conns} connections")

        # Import cantera_converter to ensure plugins are loaded
        from .cantera_converter import DualCanteraConverter

        # Create converter instance
        converter = DualCanteraConverter()
        converter._download_config_path = config_path

        if verbose:
            print("Building Cantera network...")

        # Build network (this generates the initial code)
        network = converter.build_network(validated_config)

        if verbose:
            print(f"Network built successfully with {len(network.reactors)} reactors")

        # Run simulation to generate complete runnable code
        if verbose:
            print("Running simulation to generate complete Python code...")

        # Extract simulation parameters from config
        settings = validated_config.get("settings", {})
        simulation_time = float(
            settings.get("end_time", settings.get("max_time", 10.0))
        )
        time_step = float(settings.get("dt", settings.get("time_step", 1.0)))

        if verbose:
            print(f"Simulation parameters: time={simulation_time}s, step={time_step}s")

        # Run streaming simulation to get complete code
        results, code_str = converter.run_streaming_simulation(
            simulation_time=simulation_time,
            time_step=time_step,
            config=validated_config,
        )

        if verbose:
            print(f"Simulation completed: {len(results['time'])} time points")

        # Write code to output file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(code_str)

        print(f"Python code generated: {output_path}")

        if verbose:
            print(f"Generated {len(code_str.splitlines())} lines of Python code")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _run_plugins_subcommand(argv: list[str]) -> int:
    """Handle ``boulder plugins list`` — print discovered plugin sources."""
    sub = argv[0] if argv else "list"
    if sub != "list":
        print(f"Unknown 'plugins' subcommand: {sub!r}. Use 'boulder plugins list'.")
        return 1

    from .cantera_converter import get_plugins

    plugins = get_plugins()
    ep_sources = plugins.sources.get("entry_point", [])
    env_sources = plugins.sources.get("env_var", [])

    print("Boulder plugin discovery:")
    print(f"  entry points (group 'boulder.plugins'): {len(ep_sources)} registered")
    for ep_name, ep_module in ep_sources:
        print(f"    - {ep_name}: {ep_module}")
    print(f"  BOULDER_PLUGINS env var: {len(env_sources)} registered")
    for mod_name in env_sources:
        print(f"    - {mod_name}")

    print()
    print(f"  reactor_builders       : {sorted(plugins.reactor_builders)}")
    print(f"  connection_builders    : {sorted(plugins.connection_builders)}")
    print(f"  post_build_hooks       : {len(plugins.post_build_hooks)}")
    print("  mechanism resolution   : via converter.resolve_mechanism()")
    print(f"  mechanism_switch_fn    : {plugins.mechanism_switch_fn is not None}")
    print(f"  sankey_generator       : {plugins.sankey_generator is not None}")
    print(f"  output_pane_plugins    : {len(plugins.output_pane_plugins)}")
    print(f"  summary_builders       : {sorted(plugins.summary_builders)}")
    return 0


def _run_validate_subcommand(argv: list[str]) -> int:
    """Handle ``boulder validate <yaml>`` — schema-check a STONE YAML."""
    if not argv:
        print("Error: 'boulder validate' requires a YAML path.")
        return 2
    config_path = argv[0]

    from .config import load_config_file, normalize_config, validate_config
    from .schema_registry import validate_against_plugin_schemas
    from .validation import warn_flow_device_conventions

    if not os.path.isfile(config_path):
        print(f"Error: configuration file not found: {config_path}")
        return 2

    raw = load_config_file(config_path)
    normalized = normalize_config(raw)
    validate_config(normalized)
    errors = validate_against_plugin_schemas(normalized)
    if errors:
        print(f"VALIDATION FAILED: {len(errors)} problem(s) in {config_path}")
        for err in errors:
            print(f"  - {err}")
        return 1
    notes = warn_flow_device_conventions(normalized)
    for line in notes:
        print(f"  Note: {line}")
    print(f"OK: {config_path} is a valid STONE configuration.")
    return 0


def _run_describe_subcommand(argv: list[str]) -> int:
    """Handle ``boulder describe <kind>|--list`` — dump a plugin's schema."""
    from .schema_registry import describe_kind, registered_kinds

    if not argv or argv[0] in {"-l", "--list"}:
        kinds = sorted(registered_kinds())
        if not kinds:
            print("No reactor kinds registered.")
            return 0
        print("Registered reactor kinds:")
        for k in kinds:
            print(f"  - {k}")
        return 0
    kind = argv[0]

    try:
        info = describe_kind(kind)
    except KeyError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Reactor kind: {kind}")
    print(f"  network_class       : {info['network_class']}")
    print(f"  schema              : {info['schema']}")
    if info["schema_json"]:
        import json

        print("  schema (JSON):")
        print(json.dumps(info["schema_json"], indent=2))
    if info["categories"]:
        print("  categories:")
        for side in ("inputs", "outputs"):
            print(f"    {side}:")
            for cat, keys in info["categories"].get(side, {}).items():
                print(f"      {cat}: {keys}")
    if info["default_constraints"]:
        print("  default_constraints:")
        for c in info["default_constraints"]:
            print(f"    - {c}")
    variable_maps = info.get("variable_maps") or {}
    if variable_maps:
        print("  variable_maps:")
        for side in ("inputs", "outputs"):
            side_map = variable_maps.get(side) or {}
            if not side_map:
                continue
            print(f"    {side}:")
            for key, meta in side_map.items():
                print(f"      {key}: {meta}")
    return 0


def _resolve_runner_class(dotted: str | None):
    """Resolve a dotted ``pkg.mod:Class`` string to a class object."""
    from .runner import BoulderRunner

    if dotted is None:
        return BoulderRunner
    if ":" in dotted:
        mod_name, _, cls_name = dotted.partition(":")
    else:
        mod_name, _, cls_name = dotted.rpartition(".")
    import importlib

    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


def main(argv: list[str] | None = None, *, runner_class=None) -> None:
    """Entry point for the Boulder CLI.

    Parameters
    ----------
    argv :
        Argument list (defaults to ``sys.argv[1:]``).
    runner_class :
        :class:`~boulder.runner.BoulderRunner` subclass to use for YAML
        loading and headless execution.  When ``None`` (default) the base
        ``BoulderRunner`` is used.  The ``--runner`` CLI flag is an
        alternative for shell-level overrides.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Subcommand dispatch (kept outside argparse to preserve backward-compat
    # with the flag-based invocation ``boulder path/to.yaml``).
    if argv and argv[0] in {"plugins", "validate", "describe"}:
        sub = argv[0]
        rc = 0
        if sub == "plugins":
            rc = _run_plugins_subcommand(argv[1:])
        elif sub == "validate":
            rc = _run_validate_subcommand(argv[1:])
        elif sub == "describe":
            rc = _run_describe_subcommand(argv[1:])
        sys.exit(rc)

    args = parse_args(argv)

    # --runner flag overrides the kwarg (shell users)
    if args.runner:
        runner_class = _resolve_runner_class(args.runner)
    if runner_class is None:
        from .runner import BoulderRunner

        runner_class = BoulderRunner

    # Handle --dev mode: start both backend and frontend dev server
    if args.dev:
        import subprocess
        import threading
        from pathlib import Path

        # Find the frontend directory (relative to boulder package)
        boulder_root = Path(__file__).parent.parent
        frontend_dir = boulder_root / "frontend"

        if not frontend_dir.exists():
            print(f"Error: Frontend directory not found at {frontend_dir}")
            sys.exit(1)

        print("🚀 Starting Boulder in development mode...")
        print(f"📁 Frontend directory: {frontend_dir}")

        # Start frontend dev server in a separate thread
        def run_frontend():
            try:
                # Determine npm command based on platform
                import platform

                npm_cmd = "npm.cmd" if platform.system() == "Windows" else "npm"

                # Check if node_modules exists
                if not (frontend_dir / "node_modules").exists():
                    print("📦 Installing frontend dependencies (npm install)...")
                    subprocess.run(
                        [npm_cmd, "install"],
                        cwd=frontend_dir,
                        check=True,
                        shell=True,
                    )

                print("🎨 Starting Vite dev server...")
                subprocess.run(
                    [npm_cmd, "run", "dev"],
                    cwd=frontend_dir,
                    check=True,
                    shell=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"❌ Error starting frontend dev server: {e}")
            except FileNotFoundError:
                print("❌ Error: npm not found. Please install Node.js and npm.")
                print("   Download from: https://nodejs.org/")

        frontend_thread = threading.Thread(target=run_frontend, daemon=True)
        frontend_thread.start()

        print("⚙️  Starting backend server...")

        # Open browser to Vite dev server after waiting for it to be ready
        if not args.no_open:
            import time

            def open_browser_delayed():
                # Wait longer for Vite to fully start
                print("⏳ Waiting for Vite dev server to be ready...")
                time.sleep(5)  # Increased delay for Vite to fully start
                vite_url = "http://localhost:5173"
                print(f"🌐 Opening browser at {vite_url}")
                try:
                    webbrowser.open(vite_url)
                except Exception:
                    pass

            browser_thread = threading.Thread(target=open_browser_delayed, daemon=True)
            browser_thread.start()

        # Continue to start backend below (disable opening backend URL)
        args.no_open = True

    # Handle .py files: convert first, then continue to launch GUI
    if args.config and args.config.lower().endswith(".py") and not args.headless:
        from .config import (
            load_config_file_with_py_support,
            normalize_config,
            validate_config,
        )

        # Use the unified pipeline to convert and load
        config, yaml_path = load_config_file_with_py_support(args.config, args.verbose)
        normalized = normalize_config(config)
        validated = validate_config(normalized)

        num_nodes = len(validated.get("nodes", []))
        num_conns = len(validated.get("connections", []))

        print("✅ Conversion complete!")
        print(f"📄 YAML file: {yaml_path}")
        print(f"🔧 Configuration: {num_nodes} nodes, {num_conns} connections")

        if args.verbose:
            print(f"Validated configuration successfully loaded from: {yaml_path}")

        # Update args.config to point to the generated YAML file for GUI launch
        args.config = yaml_path
        print("🚀 Launching Boulder GUI with converted configuration...")
        # Continue to GUI launch (don't return here)

    # Validate argument combinations for headless mode
    if args.download and not args.headless:
        print("Error: --download requires --headless")
        sys.exit(1)

    if args.output_yaml and not args.headless:
        print("Error: --output-yaml requires --headless")
        sys.exit(1)

    if args.headless:
        if not args.config:
            print("Error: --headless requires a config file")
            sys.exit(1)

        # .py input without --download: convert to STONE YAML and exit
        if args.config.lower().endswith(".py") and not args.download:
            from pathlib import Path

            from .parser import convert_py_to_yaml

            default_yaml = str(
                Path(args.config).with_name(Path(args.config).stem + "_stone.yaml")
            )
            output_yaml = args.output_yaml or default_yaml
            yaml_path = convert_py_to_yaml(
                args.config, output_path=output_yaml, verbose=args.verbose
            )
            print(f"STONE YAML written: {yaml_path}")
            return

        if not args.download:
            print(
                "Error: --headless requires --download (or a .py input for YAML conversion)"
            )
            sys.exit(1)

        # Run headless mode via the runner (single source of truth for both
        # `boulder` and `bloc` CLIs).
        try:
            runner = runner_class.from_yaml(args.config)
            settings = runner.config.get("settings") or {}
            end_time_val = settings.get("end_time")
            dt_val = settings.get("dt")
            runner.run_headless(
                download_path=args.download,
                simulate=True,
                end_time=float(end_time_val) if end_time_val is not None else None,
                dt=float(dt_val) if dt_val is not None else None,
            )
            print(f"Python code generated: {args.download}")
        except FileNotFoundError as exc:
            print(f"Error: Configuration file not found: {exc.filename}")
            sys.exit(1)
        except Exception as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        return

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

    import uvicorn

    # Register the converter class on the API module before uvicorn starts
    # so the lifespan handler picks it up via boulder.api.main._converter_class.
    # We import the module directly (same process – uvicorn reuses cached module).
    from boulder.api import main as _api_main

    _api_main._converter_class = getattr(runner_class, "converter_class", None)

    log_level = "info" if args.verbose else "warning"
    uvicorn.run(
        "boulder.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.debug,
        log_level=log_level,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
