"""Callbacks for cytoscape graph interactions."""

from typing import Any, Dict, List, Tuple, Union

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

    # Callback to add new reactor
    @app.callback(
        [Output("current-config", "data", allow_duplicate=True)],
        [Input("add-reactor", "n_clicks")],
        [
            State("reactor-id", "value"),
            State("reactor-type", "value"),
            State("reactor-temp", "value"),
            State("reactor-pressure", "value"),
            State("reactor-composition", "value"),
            State("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def add_reactor(
        n_clicks: int,
        reactor_id: str,
        reactor_type: str,
        temp: float,
        pressure: float,
        composition: str,
        config: dict,
    ) -> Tuple[Union[Dict[str, Any], Any]]:
        if not all([reactor_id, reactor_type, temp, pressure, composition]):
            return (dash.no_update,)
        if any(comp["id"] == reactor_id for comp in config["components"]):
            return (dash.no_update,)

        new_reactor = {
            "id": reactor_id,
            "type": reactor_type,
            "properties": {
                "temperature": temp,
                "pressure": pressure,
                "composition": composition,
            },
        }
        config["components"].append(new_reactor)
        return (config,)

    # Callback to add new MFC
    @app.callback(
        [Output("current-config", "data", allow_duplicate=True)],
        [Input("add-mfc", "n_clicks")],
        [
            State("mfc-id", "value"),
            State("mfc-source", "value"),
            State("mfc-target", "value"),
            State("mfc-flow-rate", "value"),
            State("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def add_mfc(
        n_clicks: int,
        mfc_id: str,
        source: str,
        target: str,
        flow_rate: float,
        config: dict,
    ) -> Tuple[Union[Dict[str, Any], Any]]:
        if not all([mfc_id, source, target, flow_rate]):
            return (dash.no_update,)
        if any(
            conn["source"] == source and conn["target"] == target
            for conn in config["connections"]
        ):
            return (dash.no_update,)

        new_connection = {
            "id": mfc_id,
            "type": "MassFlowController",
            "source": source,
            "target": target,
            "properties": {
                "mass_flow_rate": flow_rate,
            },
        }
        config["connections"].append(new_connection)
        return (config,)

    # Handle edge creation from store
    @app.callback(
        [Output("current-config", "data", allow_duplicate=True)],
        [Input("edge-added-store", "data")],
        [State("current-config", "data")],
        prevent_initial_call=True,
    )
    def handle_edge_creation(edge_data: dict, config: dict) -> tuple:
        if not edge_data:
            return (dash.no_update,)

        source_id = edge_data.get("source")
        target_id = edge_data.get("target")

        if not source_id or not target_id:
            return (dash.no_update,)

        # Check if this edge already exists in the config
        if any(
            conn["source"] == source_id and conn["target"] == target_id
            for conn in config["connections"]
        ):
            return (dash.no_update,)

        # Generate unique ID for the new edge
        edge_id = f"mfc_{len(config['connections']) + 1}"

        # Add new connection to config
        config["connections"].append(
            {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "type": "MassFlowController",
                "properties": {
                    "mass_flow_rate": 0.001  # Default flow rate
                },
            }
        )

        return (config,)

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
