"""Callbacks for resizable graph container."""

from typing import Any, Dict

import dash
from dash import Input, Output, State


def register_callbacks(app) -> None:  # type: ignore
    """Register resize-related callbacks."""

    @app.callback(
        Output("reactor-graph", "style"),
        Input("graph-container", "n_clicks"),
        State("reactor-graph", "style"),
        State("graph-container", "id"),
        prevent_initial_call=True,
    )
    def handle_resize_click(
        n_clicks: int, current_style: Dict[str, Any], container_id: str
    ) -> Dict[str, Any]:
        """Handle resize interactions via JavaScript."""
        if n_clicks is None:
            raise dash.exceptions.PreventUpdate

        # Preserve existing style properties
        updated_style = current_style.copy() if current_style else {}
        updated_style["width"] = "100%"
        updated_style["minHeight"] = "200px"
        updated_style["overflow"] = "hidden"

        return updated_style
