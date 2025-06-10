"""Callbacks for theme switching functionality."""

import dash
from dash import Input, Output, clientside_callback


def register_callbacks(app) -> None:  # type: ignore
    """Register theme-related callbacks."""
    # Client-side callback to detect system theme on page load
    clientside_callback(
        """
        function() {
            // Detect system theme preference
            const prefersDark = window.matchMedia &&
                window.matchMedia('(prefers-color-scheme: dark)').matches;
            const theme = prefersDark ? 'dark' : 'light';

            // Apply theme to DOM immediately
            document.documentElement.setAttribute('data-theme', theme);

            // Setup listener for theme preference changes
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
                document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            });

            console.log('System theme detected:', theme);

            return theme;
        }
        """,
        Output("theme-store", "data"),
        [Input("app-container", "id")],  # Use app container as a simple trigger
        prevent_initial_call=False,
    )

    # Callback to select reactor graph node when hovering over Sankey nodes
    @app.callback(
        [
            Output("reactor-graph", "selectedNodeData"),
            Output("reactor-graph", "stylesheet"),
        ],
        [
            Input("theme-store", "data"),
            Input("sankey-plot", "hoverData"),
        ],
        prevent_initial_call=False,
    )
    def update_cytoscape_selection(theme: str, hover_data):
        """Select reactor graph node when hovering over Sankey nodes and update stylesheet."""
        import copy

        from ..styles import get_cytoscape_stylesheet

        # Get the base stylesheet for the current theme
        base_stylesheet = get_cytoscape_stylesheet(theme)

        # Get the callback context to see what triggered this callback
        ctx = dash.callback_context
        if not ctx.triggered:
            return [], base_stylesheet

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        triggered_prop = ctx.triggered[0]["prop_id"].split(".")[1]

        # Check for Sankey hover interaction
        if (
            triggered_id == "sankey-plot"
            and triggered_prop == "hoverData"
            and hover_data
            and hover_data.get("points")
        ):
            # Get the node label from Sankey diagram (now should match reactor graph ID)
            hovered_point = hover_data["points"][0]

            if "label" in hovered_point:
                reactor_node_id = hovered_point["label"]
                print(f"[DEBUG] Hovering over Sankey node: '{reactor_node_id}'")

                # Create selected node data to programmatically select the node
                selected_node_data = [{"id": reactor_node_id}]
                print(f"[DEBUG] Setting selectedNodeData: {selected_node_data}")

                # Also update stylesheet with highlight using direct node selector
                new_stylesheet = copy.deepcopy(base_stylesheet)

                # Remove any existing node-specific highlight styles
                new_stylesheet = [
                    style
                    for style in new_stylesheet
                    if not (
                        style.get("selector", "").startswith("node[id")
                        and "border-width" in str(style.get("style", {}))
                    )
                ]

                # Add highlight style for the selected node
                if theme == "dark":
                    highlight_color = "#FFD700"  # Gold for dark theme
                    border_color = "#FFA500"  # Orange border
                else:
                    highlight_color = "#FF6B6B"  # Red for light theme
                    border_color = "#DC3545"  # Darker red border

                # Use direct node ID selector instead of :selected
                highlight_style = {
                    "selector": f"node[id = '{reactor_node_id}']",
                    "style": {
                        "background-color": highlight_color,
                        "border-width": "8px",
                        "border-color": border_color,
                        "border-style": "solid",
                        "z-index": 999,
                        "text-outline-color": border_color,
                        "text-outline-width": 4,
                    },
                }

                new_stylesheet.append(highlight_style)
                print(f"[DEBUG] Added highlight style: {highlight_style}")
                print(f"[DEBUG] Total stylesheet entries: {len(new_stylesheet)}")

                return selected_node_data, new_stylesheet

        # For theme changes or other triggers, return empty selection and base stylesheet
        return [], base_stylesheet
