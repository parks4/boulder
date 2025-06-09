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
            Input("add-reactor", "n_clicks"),
            Input("add-mfc", "n_clicks"),
            Input("upload-config", "contents"),
            Input("delete-config-file", "n_clicks"),
            Input("save-config-json-edit-btn", "n_clicks"),
            Input("edge-added-store", "data"),
            Input("run-simulation", "n_clicks"),
            Input("reactor-graph", "selectedNodeData"),
            Input("reactor-graph", "selectedEdgeData"),
            Input("current-config", "data"),
        ],
        [
            State("reactor-id", "value"),
            State("reactor-type", "value"),
            State("reactor-temp", "value"),
            State("reactor-pressure", "value"),
            State("reactor-composition", "value"),
            State("mfc-id", "value"),
            State("mfc-source", "value"),
            State("mfc-target", "value"),
            State("mfc-flow-rate", "value"),
            State("upload-config", "filename"),
            State("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def notification_handler(
        add_reactor_click: int,
        add_mfc_click: int,
        upload_contents: str,
        delete_config_click: int,
        save_edit_click: int,
        edge_data: dict,
        run_sim_click: int,
        selected_node: list,
        selected_edge: list,
        config_data: dict,
        reactor_id: str,
        reactor_type: str,
        reactor_temp: float,
        reactor_pressure: float,
        reactor_composition: str,
        mfc_id: str,
        mfc_source: str,
        mfc_target: str,
        mfc_flow_rate: float,
        upload_filename: str,
        config: dict,
    ):
        """Handle the various events that can trigger the notification toast."""
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

        # Add Reactor
        if trigger == "add-reactor" and add_reactor_click:
            if not all(
                [
                    reactor_id,
                    reactor_type,
                    reactor_temp,
                    reactor_pressure,
                    reactor_composition,
                ]
            ):
                return True, "Please fill in all fields", "Error", "danger"
            if any(comp["id"] == reactor_id for comp in config["components"]):
                return (
                    True,
                    f"Component with ID {reactor_id} already exists",
                    "Error",
                    "danger",
                )
            return True, f"Added {reactor_type} {reactor_id}", "Success", "success"

        # Add MFC
        if trigger == "add-mfc" and add_mfc_click:
            if not all([mfc_id, mfc_source, mfc_target, mfc_flow_rate]):
                return True, "Please fill in all fields", "Error", "danger"
            if any(
                conn["source"] == mfc_source and conn["target"] == mfc_target
                for conn in config["connections"]
            ):
                return (
                    True,
                    f"Connection from {mfc_source} to {mfc_target} already exists",
                    "Error",
                    "danger",
                )
            return (
                True,
                f"Added MFC {mfc_id} from {mfc_source} to {mfc_target}",
                "Success",
                "success",
            )

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
        if trigger == "save-config-json-edit-btn" and save_edit_click:
            return (
                True,
                "✅ Configuration updated from editor.",
                "Success",
                "success",
            )

        # Edge creation
        if trigger == "edge-added-store" and edge_data:
            if edge_data and edge_data.get("source") and edge_data.get("target"):
                return (
                    True,
                    f"Added connection from {edge_data['source']} to {edge_data['target']}",
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
                element_type = data.get('type', 'Element')
                element_id = data.get('id', 'Unknown')
                return (
                    True,
                    f"Viewing properties of {element_type} {element_id}",
                    "Info",
                    "info",
                )

        # Graph update
        if trigger == "current-config":
            return True, "Graph updated", "Info", "info"

        return False, "", "", "primary"
