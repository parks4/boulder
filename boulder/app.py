import os

import dash
import dash_bootstrap_components as dbc

from . import callbacks
from .config import (
    get_config_from_path_with_comments,
    get_initial_config,
    get_initial_config_with_comments,
)
from .layout import get_layout
from .styles import CYTOSCAPE_STYLESHEET

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
        initial_config, original_yaml = get_config_from_path_with_comments(
            env_config_path.strip()
        )
    else:
        initial_config, original_yaml = get_initial_config_with_comments()
except Exception as e:
    print(f"Warning: Could not load config with comments, using standard loader: {e}")
    initial_config = get_initial_config()
    original_yaml = ""

# Set the layout
app.layout = get_layout(initial_config, CYTOSCAPE_STYLESHEET, original_yaml)

# Register all callbacks
callbacks.register_callbacks(app)


def run_server(debug: bool = False, host: str = "0.0.0.0", port: int = 8050) -> None:
    """Run the Dash server."""
    app.run(debug=debug, host=host, port=port)
