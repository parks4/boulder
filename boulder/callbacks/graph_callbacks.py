"""Callbacks for cytoscape graph interactions."""

import time
from typing import Any, Dict, List, Tuple

import dash
from dash import Input, Output, State


def register_callbacks(app) -> None:  # type: ignore
    """Register graph-related callbacks."""

    # Callback to update the graph
    @app.callback(
        [Output("reactor-graph", "elements")],
        [Input("current-config", "data")],
        prevent_initial_call=False,
    )
    def update_graph(config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]]]:
        from ..utils import config_to_cyto_elements

        return (config_to_cyto_elements(config),)

    # STEP 1: Trigger reactor addition and close modal immediately
    @app.callback(
        [
            Output("add-reactor-modal", "is_open", allow_duplicate=True),
            Output("add-reactor-trigger", "data"),
        ],
        Input("add-reactor", "n_clicks"),
        [
            State("reactor-id", "value"),
            State("reactor-type", "value"),
            State("reactor-temp", "value"),
            State("reactor-pressure", "value"),
            State("reactor-composition", "value"),
        ],
        prevent_initial_call=True,
    )
    def trigger_reactor_addition(
        n_clicks: int,
        reactor_id: str,
        reactor_type: str,
        temp: float,
        pressure: float,
        composition: str,
    ) -> Tuple[bool, Any]:
        if not all([reactor_id, reactor_type, temp, pressure, composition]):
            # Keep modal open for user to complete form
            return (True, dash.no_update)

        payload = {
            "id": reactor_id,
            "type": reactor_type,
            "properties": {
                "temperature": temp,
                "pressure": pressure,
                "composition": composition,
            },
            "timestamp": time.time(),  # Ensures change fires
        }
        return (False, payload)  # Close modal, trigger step 2

    # STEP 2: Update config from trigger
    @app.callback(
        Output("current-config", "data", allow_duplicate=True),
        Input("add-reactor-trigger", "data"),
        State("current-config", "data"),
        prevent_initial_call=True,
    )
    def add_reactor(trigger_data: dict, config: dict) -> Any:
        if not trigger_data:
            raise dash.exceptions.PreventUpdate

        new_reactor = {
            "id": trigger_data["id"],
            "type": trigger_data["type"],
            "properties": trigger_data["properties"],
        }
        if any(comp["id"] == new_reactor["id"] for comp in config["components"]):
            return dash.no_update

        new_components = [*config.get("components", []), new_reactor]
        new_config = {**config, "components": new_components}
        return new_config

    # STEP 1: Trigger MFC addition and close modal immediately
    @app.callback(
        [
            Output("add-mfc-modal", "is_open", allow_duplicate=True),
            Output("add-mfc-trigger", "data"),
        ],
        Input("add-mfc", "n_clicks"),
        [
            State("mfc-id", "value"),
            State("mfc-source", "value"),
            State("mfc-target", "value"),
            State("mfc-flow-rate", "value"),
        ],
        prevent_initial_call=True,
    )
    def trigger_mfc_addition(
        n_clicks: int,
        mfc_id: str,
        source: str,
        target: str,
        flow_rate: float,
    ) -> Tuple[bool, Any]:
        if not all([mfc_id, source, target, flow_rate]):
            return (True, dash.no_update)

        payload = {
            "id": mfc_id,
            "source": source,
            "target": target,
            "mass_flow_rate": flow_rate,
            "timestamp": time.time(),
        }
        return (False, payload)

    # STEP 2: Update config from trigger
    @app.callback(
        Output("current-config", "data", allow_duplicate=True),
        Input("add-mfc-trigger", "data"),
        State("current-config", "data"),
        prevent_initial_call=True,
    )
    def add_mfc(trigger_data: dict, config: dict) -> Any:
        if not trigger_data:
            raise dash.exceptions.PreventUpdate

        if any(
            conn["source"] == trigger_data["source"]
            and conn["target"] == trigger_data["target"]
            for conn in config["connections"]
        ):
            return dash.no_update

        new_connection = {
            "id": trigger_data["id"],
            "type": "MassFlowController",
            "source": trigger_data["source"],
            "target": trigger_data["target"],
            "properties": {
                "mass_flow_rate": trigger_data["mass_flow_rate"],
            },
        }
        new_connections = [*config.get("connections", []), new_connection]
        new_config = {**config, "connections": new_connections}
        return new_config

    # Update last-selected-element on selection
    @app.callback(
        Output("last-selected-element", "data"),
        [
            Input("reactor-graph", "selectedNodeData"),
            Input("reactor-graph", "selectedEdgeData"),
        ],
        prevent_initial_call=True,
    )
    def update_last_selected(node_data, edge_data):
        if node_data:
            return {"type": "node", "data": node_data[0]}
        elif edge_data:
            return {"type": "edge", "data": edge_data[0]}
        return {}

    # After Save, re-trigger last-selected-element to force update
    @app.callback(
        Output("last-selected-element", "data", allow_duplicate=True),
        [Input("properties-save-btn", "n_clicks")],
        [State("last-selected-element", "data")],
        prevent_initial_call=True,
    )
    def retrigger_last_selected(n_clicks, last_selected):
        if n_clicks:
            return last_selected
        raise dash.exceptions.PreventUpdate
