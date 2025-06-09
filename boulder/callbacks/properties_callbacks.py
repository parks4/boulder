"""Callbacks for properties panel editing and display."""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html


def register_callbacks(app) -> None:  # type: ignore
    """Register properties-related callbacks."""

    # Callback to show properties of selected element (editable)
    @app.callback(
        Output("properties-panel", "children"),
        [
            Input("last-selected-element", "data"),
            Input("properties-edit-mode", "data"),
            Input("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def show_properties_editable(last_selected, edit_mode, config):
        from ..utils import label_with_unit

        node_data = None
        edge_data = None
        if last_selected and last_selected.get("type") == "node":
            node_id = last_selected["data"]["id"]
            # Find the latest node data from config
            for comp in config["components"]:
                if comp["id"] == node_id:
                    node_data = [comp]
                    break
        elif last_selected and last_selected.get("type") == "edge":
            edge_id = last_selected["data"]["id"]
            for conn in config["connections"]:
                if conn["id"] == edge_id:
                    edge_data = [conn]
                    break

        if node_data:
            data = node_data[0]
            properties = data.get("properties", {})
            if edit_mode:
                fields = [
                    dbc.Row(
                        [
                            dbc.Col(html.Label(label_with_unit(k)), width=6),
                            dbc.Col(
                                dcc.Input(
                                    id={"type": "prop-edit", "prop": k},
                                    value=str(v),
                                    type="text",
                                    style={"width": "100%"},
                                ),
                                width=6,
                            ),
                        ],
                        className="mb-2",
                    )
                    for k, v in properties.items()
                ]
                return html.Div(
                    [
                        html.H4(f"{data['id']} ({data['type']})"),
                        html.Div(fields),
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.Button(
                                        "Save",
                                        id="properties-save-btn",
                                        n_clicks=0,
                                        style={"display": "inline-block"},
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    html.Button(
                                        "Edit",
                                        id="properties-edit-btn",
                                        n_clicks=0,
                                        style={"display": "none"},
                                    ),
                                    width="auto",
                                ),
                            ],
                            className="mt-3",
                        ),
                    ]
                )
            else:
                fields = [
                    dbc.Row(
                        [
                            dbc.Col(html.Label(label_with_unit(k)), width=6),
                            dbc.Col(
                                html.Div(str(v), style={"wordBreak": "break-all"}),
                                width=6,
                            ),
                        ],
                        className="mb-2",
                    )
                    for k, v in properties.items()
                ]
                return html.Div(
                    [
                        html.H4(f"{data['id']} ({data['type']})"),
                        html.Div(fields),
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.Button(
                                        "Save",
                                        id="properties-save-btn",
                                        n_clicks=0,
                                        style={"display": "none"},
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    html.Button(
                                        "Edit",
                                        id="properties-edit-btn",
                                        n_clicks=0,
                                        style={"display": "inline-block"},
                                    ),
                                    width="auto",
                                ),
                            ],
                            className="mt-3",
                        ),
                    ]
                )
        elif edge_data:
            data = edge_data[0]
            properties = data.get("properties", {})
            if edit_mode:
                fields = [
                    dbc.Row(
                        [
                            dbc.Col(html.Label(label_with_unit(k)), width=5),
                            dbc.Col(
                                dcc.Input(
                                    id={"type": "prop-edit", "prop": k},
                                    value=str(v),
                                    type="text",
                                    style={"width": "100%"},
                                ),
                                width=7,
                            ),
                        ],
                        className="mb-2",
                    )
                    for k, v in properties.items()
                ]
                return html.Div(
                    [
                        html.H4(f"{data['id']} ({data['type']})"),
                        html.Div(fields),
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.Button(
                                        "Save",
                                        id="properties-save-btn",
                                        n_clicks=0,
                                        style={"display": "inline-block"},
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    html.Button(
                                        "Edit",
                                        id="properties-edit-btn",
                                        n_clicks=0,
                                        style={"display": "none"},
                                    ),
                                    width="auto",
                                ),
                            ],
                            className="mt-3",
                        ),
                    ]
                )
            else:
                fields = [
                    dbc.Row(
                        [
                            dbc.Col(html.Label(label_with_unit(k)), width=5),
                            dbc.Col(
                                html.Div(str(v), style={"wordBreak": "break-all"}),
                                width=7,
                            ),
                        ],
                        className="mb-2",
                    )
                    for k, v in properties.items()
                ]
                return html.Div(
                    [
                        html.H4(f"{data['id']} ({data['type']})"),
                        html.Div(fields),
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.Button(
                                        "Save",
                                        id="properties-save-btn",
                                        n_clicks=0,
                                        style={"display": "none"},
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    html.Button(
                                        "Edit",
                                        id="properties-edit-btn",
                                        n_clicks=0,
                                        style={"display": "inline-block"},
                                    ),
                                    width="auto",
                                ),
                            ],
                            className="mt-3",
                        ),
                    ]
                )
        return html.Div("Select a node or edge to view properties")

    # Callback to toggle properties edit mode
    @app.callback(
        Output("properties-edit-mode", "data"),
        [
            Input("properties-edit-btn", "n_clicks"),
            Input("properties-save-btn", "n_clicks"),
        ],
        [State("properties-edit-mode", "data")],
        prevent_initial_call=True,
    )
    def toggle_properties_edit_mode(edit_n, save_n, edit_mode):
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "properties-edit-btn" and edit_n:
            return True
        elif trigger == "properties-save-btn" and save_n:
            return False
        return edit_mode

    # Callback to save edited properties
    @app.callback(
        Output("current-config", "data", allow_duplicate=True),
        [Input("properties-save-btn", "n_clicks")],
        [
            State("reactor-graph", "selectedNodeData"),
            State("reactor-graph", "selectedEdgeData"),
            State("current-config", "data"),
            State({"type": "prop-edit", "prop": dash.ALL}, "value"),
            State({"type": "prop-edit", "prop": dash.ALL}, "id"),
        ],
        prevent_initial_call=True,
    )
    def save_properties(n_clicks, node_data, edge_data, config, values, ids):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        if node_data:
            data = node_data[0]
            comp_id = data["id"]
            for comp in config["components"]:
                if comp["id"] == comp_id:
                    # Ensure properties dict exists
                    if "properties" not in comp:
                        comp["properties"] = {}
                    for v, i in zip(values, ids):
                        key = i["prop"]
                        # Convert to float if key is temperature or pressure
                        if key in ("temperature", "pressure"):
                            try:
                                comp["properties"][key] = float(v)
                            except Exception:
                                comp["properties"][key] = v
                        else:
                            comp["properties"][key] = v
                    break
        elif edge_data:
            data = edge_data[0]
            conn_id = data["id"]
            for conn in config["connections"]:
                if conn["id"] == conn_id:
                    # Ensure properties dict exists
                    if "properties" not in conn:
                        conn["properties"] = {}
                    for v, i in zip(values, ids):
                        key = i["prop"]
                        # Map 'flow_rate' to 'mass_flow_rate' for MassFlowController
                        if conn["type"] == "MassFlowController" and key == "flow_rate":
                            try:
                                conn["properties"]["mass_flow_rate"] = float(v)
                            except Exception:
                                conn["properties"]["mass_flow_rate"] = v
                            # Optionally remove old key
                            if "flow_rate" in conn["properties"]:
                                del conn["properties"]["flow_rate"]
                        else:
                            conn["properties"][key] = v
                    break
        return config
