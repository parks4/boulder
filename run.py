"""Entry point for running the Blocscape application."""

from blocscape.app import run_server
import dash_html_components as html

if __name__ == "__main__":
    run_server(debug=True)  # Enable debug mode to see errors in the browser

# Add this somewhere in your layout, e.g. at the end: (this is for the config file upload)
html.Div([
    html.Button("✕", id="delete-config-file", style={"display": "none"}),
    html.Span("", id="config-file-name-span", style={"display": "none"}),
], style={"display": "none"})
