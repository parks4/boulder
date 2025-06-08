import dash
import dash_bootstrap_components as dbc

from .config import get_initial_config
from .styles import CYTOSCAPE_STYLESHEET
from .layout import get_layout
from . import callbacks

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
    ],
    title="Blocscape",
)
server = app.server  # Expose the server for deployment

# Load initial configuration
initial_config = get_initial_config()

# Set the layout
app.layout = get_layout(initial_config, CYTOSCAPE_STYLESHEET)

# Register all callbacks
callbacks.register_callbacks(app)


def run_server(debug: bool = False) -> None:
    """Run the Dash server."""
    app.run(debug=debug, host="0.0.0.0", port=8050)
