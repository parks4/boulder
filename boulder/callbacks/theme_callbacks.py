"""Callbacks for theme switching functionality."""

from dash import Input, Output, clientside_callback


def register_callbacks(app) -> None:  # type: ignore
    """Register theme-related callbacks."""
    # Client-side callback to detect system theme on page load
    clientside_callback(
        """
        function() {
            // Detect system theme preference
            const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
            const theme = prefersDark ? 'dark' : 'light';

            // Apply theme to DOM immediately
            document.documentElement.setAttribute('data-theme', theme);

            console.log('System theme detected:', theme);

            return theme;
        }
        """,
        Output("theme-store", "data"),
        [Input("app-container", "id")],  # Use app container as a simple trigger
        prevent_initial_call=False,
    )

    # Callback to update Cytoscape stylesheet based on theme
    @app.callback(
        Output("reactor-graph", "stylesheet"),
        [Input("theme-store", "data")],
        prevent_initial_call=False,
    )
    def update_cytoscape_stylesheet(theme: str):
        """Update Cytoscape stylesheet based on current theme."""
        from ..styles import get_cytoscape_stylesheet

        return get_cytoscape_stylesheet(theme)
