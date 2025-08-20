import logging
import os

import dash
import dash_bootstrap_components as dbc

# Import cantera_converter early to ensure plugins are loaded at app startup
from . import (
    callbacks,
    cantera_converter,  # noqa: F401
    output_pane_plugins,  # noqa: F401
)
from .config import (
    get_config_from_path_with_comments,
    get_initial_config_with_comments,
)
from .layout import get_layout
from .styles import CYTOSCAPE_STYLESHEET

# Create a single, shared converter instance for the app
# This ensures that the same set of discovered plugins is used everywhere.
CONVERTER = cantera_converter.DualCanteraConverter()


# Initialize the Dash app with Bootstrap
app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.7.2/font/bootstrap-icons.css",
    ],
    external_scripts=[
        "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdn.jsdelivr.net/npm/cytoscape-edgehandles@4.0.1/cytoscape-edgehandles.min.js",
        # Dagre layout dependencies for left-to-right graph orientation
        "https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js",
        "https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js",
    ],
    title="Boulder",
)
server = app.server  # Expose the server for deployment

# Load initial configuration with optional override via environment variable
# Allow overriding the initial configuration via environment variable
# Use either BOULDER_CONFIG_PATH or BOULDER_CONFIG for convenience
env_config_path = os.environ.get("BOULDER_CONFIG_PATH") or os.environ.get(
    "BOULDER_CONFIG"
)

if env_config_path and env_config_path.strip():
    cleaned = env_config_path.strip()
    initial_config, original_yaml = get_config_from_path_with_comments(cleaned)
    # When a specific file is provided, propagate its base name to the UI store
    provided_filename = os.path.basename(cleaned)
else:
    initial_config, original_yaml = get_initial_config_with_comments()


# Set the layout
app.layout = get_layout(
    initial_config,
    CYTOSCAPE_STYLESHEET,
    original_yaml,
    config_filename=locals().get("provided_filename", ""),
)

# Register all callbacks
callbacks.register_callbacks(app)


def run_server(
    debug: bool = False, host: str = "0.0.0.0", port: int = 8050, verbose: bool = False
) -> None:
    """Run the Dash server."""
    if verbose:
        # Configure logging for verbose output
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        logger = logging.getLogger(__name__)
        logger.info("Boulder server starting in verbose mode")
        logger.info(f"Server configuration: host={host}, port={port}, debug={debug}")

        # Check for potential port conflicts and log them
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
                logger.info(f"Port {port} is available for binding")
        except OSError as e:
            logger.warning(
                f"Port {port} binding check failed: {e} "
                f"(this is normal if CLI already handled port conflicts)"
            )

        # Log initial configuration details
        env_config_path = os.environ.get("BOULDER_CONFIG_PATH") or os.environ.get(
            "BOULDER_CONFIG"
        )
        if env_config_path:
            logger.info(f"Loading configuration from: {env_config_path}")
        else:
            logger.info("Using default configuration")

    app.run(debug=debug, host=host, port=port)
