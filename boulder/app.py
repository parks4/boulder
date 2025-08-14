import os

import dash
import dash_bootstrap_components as dbc

# Import cantera_converter early to ensure plugins are loaded at app startup
from . import (
    callbacks,
    cantera_converter,  # noqa: F401
)
from .config import (
    get_config_from_path_with_comments,
    get_initial_config,
    get_initial_config_with_comments,
)
from .layout import get_layout
from .styles import CYTOSCAPE_STYLESHEET

# Create a single, shared converter instance for the app
# This ensures that the same set of discovered plugins is used everywhere.
CONVERTER = cantera_converter.CanteraConverter()

# Global variable to track debug mode
_debug_mode = False

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
try:
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
except Exception as e:
    print(f"Warning: Could not load config with comments, using standard loader: {e}")
    initial_config = get_initial_config()
    original_yaml = ""

# Register all callbacks
callbacks.register_callbacks(app)


def create_app(debug: bool = False) -> dash.Dash:
    """Create and configure the Boulder app for testing.

    This function sets up the app with the proper layout and configuration
    without running the server, making it suitable for testing.

    Args:
        debug: If True, enables debug mode with console forwarding

    Returns
    -------
        dash.Dash: The configured Dash application
    """
    global _debug_mode
    _debug_mode = debug

    # Set the layout with debug mode
    app.layout = get_layout(
        initial_config,
        CYTOSCAPE_STYLESHEET,
        original_yaml,
        config_filename=locals().get("provided_filename", ""),
        debug=debug,
    )

    # If debug mode is enabled, register console callbacks
    if debug:
        from .callbacks import console_callbacks

        console_callbacks.register_callbacks(app)

    return app


def run_server(debug: bool = False, host: str = "0.0.0.0", port: int = 8050) -> None:
    """Run the Dash server.

    This function initializes and starts the Boulder Dash application server.
    When debug mode is enabled, it also sets up console forwarding functionality
    to capture browser console messages and display them in the server console.

    Args:
        debug: If True, enables debug mode with console forwarding and detailed
               error reporting. Browser console messages will be forwarded to
               the server console with timestamps and color coding.
        host: The host interface to bind the server to (default: "0.0.0.0")
        port: The port number to bind the server to (default: 8050)

    Debug Mode Features:
        - Console forwarding: Browser console messages appear in server console
        - Enhanced error reporting: More detailed error information
        - Development tools: Additional debugging capabilities
    """
    # Configure the app using create_app
    create_app(debug)

    # Run the server
    app.run(debug=debug, host=host, port=port)


def is_debug_mode() -> bool:
    """Check if the app is running in debug mode."""
    return _debug_mode
