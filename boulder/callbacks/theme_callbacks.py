"""Callbacks for theme switching functionality."""

import dash
from dash import Input, Output, clientside_callback, ClientsideFunction


def register_callbacks(app) -> None:  # type: ignore
    """Register theme-related callbacks."""
    
    # Callback to update theme store when switch is toggled
    @app.callback(
        Output("theme-store", "data"),
        [Input("theme-switch", "value")],
        prevent_initial_call=False,
    )
    def update_theme_store(is_dark: bool) -> str:
        """Update the theme store based on switch state."""
        return "dark" if is_dark else "light"
    
    # Client-side callback to apply theme changes to the DOM and save to localStorage
    clientside_callback(
        """
        function(theme) {
            const html = document.documentElement;
            
            if (theme === 'dark') {
                html.setAttribute('data-theme', 'dark');
                localStorage.setItem('boulder-theme', 'dark');
            } else {
                html.setAttribute('data-theme', 'light');
                localStorage.setItem('boulder-theme', 'light');
            }
            
            return theme;
        }
        """,
        Output("app-container", "data-theme"),
        [Input("theme-store", "data")],
        prevent_initial_call=False,
    )
    
    # Client-side callback to initialize theme from localStorage on page load
    clientside_callback(
        """
        function(n_intervals) {
            if (n_intervals === 0) {
                const savedTheme = localStorage.getItem('boulder-theme') || 'light';
                const themeSwitch = document.getElementById('theme-switch');
                if (themeSwitch) {
                    themeSwitch.checked = savedTheme === 'dark';
                }
                return savedTheme === 'dark';
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("theme-switch", "value"),
        [Input("init-interval", "n_intervals")],
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