import dash
import dash_bootstrap_components as dbc
from .layout import layout
from .callbacks import register_all_callbacks
from .config import DEFAULT_THEME

app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    external_stylesheets=[getattr(dbc.themes, DEFAULT_THEME), "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.7.2/font/bootstrap-icons.css"],
    external_scripts=[
        "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdn.jsdelivr.net/npm/cytoscape-edgehandles@4.0.1/cytoscape-edgehandles.min.js",
    ],
    title="Blocscape",
)
server = app.server

app.layout = layout

register_all_callbacks(app)

def run_server(debug=True, **kwargs):
    """Run the Dash server with the given parameters."""
    app.run(debug=debug, **kwargs)

if __name__ == "__main__":
    run_server(debug=True)
