"""Callbacks for toast notifications."""

import base64
import json

import dash
from dash import Input, Output, State


def register_callbacks(app) -> None:  # type: ignore
    """Register notification-related callbacks."""

    @app.callback(
        [
            Output("notification-toast", "is_open"),
            Output("notification-toast", "children"),
            Output("notification-toast", "header"),
            Output("notification-toast", "icon"),
        ],
        [
            Input("upload-config", "contents"),
            Input("delete-config-file", "n_clicks"),
            Input("save-config-yaml-edit-btn", "n_clicks"),
            Input("run-simulation", "n_clicks"),
            Input("reactor-graph", "selectedNodeData"),
            Input("reactor-graph", "selectedEdgeData"),
        ],
        [
            State("upload-config", "filename"),
            State("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def notification_handler(
        upload_contents: str,
        delete_config_click: int,
        save_edit_click: int,
        run_sim_click: int,
        selected_node: list,
        selected_edge: list,
        upload_filename: str,
        config: dict,
    ):
        """Handle the various events that can trigger the notification toast."""
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

        # Config upload
        if trigger == "upload-config" and upload_contents:
            try:
                content_type, content_string = upload_contents.split(",")
                decoded_string = base64.b64decode(content_string).decode("utf-8")
                json.loads(decoded_string)
                return (
                    True,
                    f"✅ Configuration loaded from {upload_filename}",
                    "Success",
                    "success",
                )
            except Exception:
                return (
                    True,
                    f"Could not parse file {upload_filename}.",
                    "Error",
                    "danger",
                )

        # Config delete
        if trigger == "delete-config-file" and delete_config_click:
            return True, "Config file removed.", "Success", "success"

        # Config edit
        if trigger == "save-config-yaml-edit-btn" and save_edit_click:
            return (
                True,
                "✅ Configuration updated from editor.",
                "Success",
                "success",
            )

        # Run simulation
        if trigger == "run-simulation" and run_sim_click:
            return True, "Simulation successfully started", "Success", "success"

        # Show properties
        if trigger == "reactor-graph" and (selected_node or selected_edge):
            data = (
                (selected_node or selected_edge)[0]
                if (selected_node or selected_edge)
                else None
            )
            if data:
                # Use .get() to safely access 'type' key with fallback
                element_type = data.get("type", "Element")
                element_id = data.get("id", "Unknown")
                return (
                    True,
                    f"Viewing properties of {element_type} {element_id}",
                    "Info",
                    "info",
                )

        return False, "", "", "primary"
