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
        "--dev",
        action="store_true",
        help="Run the development frontend (starts both backend and Vite dev server)",
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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

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

    if args.headless:
        if not args.config:
            print("Error: --headless requires a config file")
            sys.exit(1)
        if not args.download:
            print("Error: --headless requires --download")
            sys.exit(1)

        # Run headless mode
        run_headless_mode(args.config, args.download, args.verbose)
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
