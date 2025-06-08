from dash import Input, Output, State, callback_context, ALL
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc


def register_properties_callbacks(app):
    @app.callback(
        Output("properties-panel", "children"),
        [Input("last-selected-element", "data"), Input("properties-edit-mode", "data"), Input("current-config", "data")],
        prevent_initial_call=True,
    )
    def show_properties_editable(last_selected, edit_mode, config):
        if not last_selected:
            return html.Div("Select a node or edge to view properties")

        node_data = None
        edge_data = None
        if last_selected.get("type") == "node":
            node_id = last_selected["data"]["id"]
            for comp in config["components"]:
                if comp["id"] == node_id:
                    node_data = [comp]
                    break
        elif last_selected.get("type") == "edge":
            edge_id = last_selected["data"]["id"]
            for conn in config["connections"]:
                if conn["id"] == edge_id:
                    edge_data = [conn]
                    break

        def label_with_unit(k):
            if k == "pressure":
                return f"{k} (Pa)"
            elif k == "composition":
                return f"{k} (%mol)"
            elif k == "temperature":
                return f"{k} (K)"
            elif k == "mass_flow_rate":
                return f"{k} (kg/s)"
            return k

        if node_data:
            data = node_data[0]
            properties = data["properties"]
            if edit_mode:
                fields = [
                    dbc.Row([
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
                    ], className="mb-2")
                    for k, v in properties.items()
                ]
                return html.Div([
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row([
                        dbc.Col(html.Button("Save", id="properties-save-btn", n_clicks=0, style={"display": "inline-block"}), width="auto"),
                        dbc.Col(html.Button("Edit", id="properties-edit-btn", n_clicks=0, style={"display": "none"}), width="auto"),
                    ], className="mt-3"),
                ])
            else:
                fields = [
                    dbc.Row([
                        dbc.Col(html.Label(label_with_unit(k)), width=6),
                        dbc.Col(html.Div(str(v), style={"wordBreak": "break-all"}), width=6),
                    ], className="mb-2")
                    for k, v in properties.items()
                ]
                return html.Div([
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row([
                        dbc.Col(html.Button("Save", id="properties-save-btn", n_clicks=0, style={"display": "none"}), width="auto"),
                        dbc.Col(html.Button("Edit", id="properties-edit-btn", n_clicks=0, style={"display": "inline-block"}), width="auto"),
                    ], className="mt-3"),
                ])
        elif edge_data:
            data = edge_data[0]
            properties = data["properties"]
            if edit_mode:
                fields = [
                    dbc.Row([
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
                    ], className="mb-2")
                    for k, v in properties.items()
                ]
                return html.Div([
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row([
                        dbc.Col(html.Button("Save", id="properties-save-btn", n_clicks=0, style={"display": "inline-block"}), width="auto"),
                        dbc.Col(html.Button("Edit", id="properties-edit-btn", n_clicks=0, style={"display": "none"}), width="auto"),
                    ], className="mt-3"),
                ])
            else:
                fields = [
                    dbc.Row([
                        dbc.Col(html.Label(label_with_unit(k)), width=5),
                        dbc.Col(html.Div(str(v), style={"wordBreak": "break-all"}), width=7),
                    ], className="mb-2")
                    for k, v in properties.items()
                ]
                return html.Div([
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row([
                        dbc.Col(html.Button("Save", id="properties-save-btn", n_clicks=0, style={"display": "none"}), width="auto"),
                        dbc.Col(html.Button("Edit", id="properties-edit-btn", n_clicks=0, style={"display": "inline-block"}), width="auto"),
                    ], className="mt-3"),
                ])
        return html.Div("Select a node or edge to view properties")

    @app.callback(
        Output("properties-edit-mode", "data"),
        [Input("properties-edit-btn", "n_clicks"), Input("properties-save-btn", "n_clicks")],
        [State("properties-edit-mode", "data")],
        prevent_initial_call=True,
    )
    def toggle_properties_edit_mode(edit_n, save_n, current_mode):
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "properties-edit-btn" and edit_n:
            return True
        elif trigger == "properties-save-btn" and save_n:
            return False
        return current_mode

    @app.callback(
        Output("current-config", "data", allow_duplicate=True),
        [Input("properties-save-btn", "n_clicks")],
        [
            State("last-selected-element", "data"),
            State("current-config", "data"),
            State({"type": "prop-edit", "prop": ALL}, "value"),
            State({"type": "prop-edit", "prop": ALL}, "id"),
        ],
        prevent_initial_call=True,
    )
    def save_properties(n_clicks, selected_element, config, values, ids):
        if not n_clicks or not selected_element:
            raise dash.exceptions.PreventUpdate

        element_id = selected_element["data"]["id"]
        element_type = selected_element["type"]
        
        # Find the element in the config
        if element_type == "node":
            for comp in config["components"]:
                if comp["id"] == element_id:
                    for v, i in zip(values, ids):
                        key = i["prop"]
                        if key in ("temperature", "pressure"):
                            try:
                                comp["properties"][key] = float(v)
                            except Exception:
                                comp["properties"][key] = v
                        else:
                            comp["properties"][key] = v
                    break
        else:  # edge
            for conn in config["connections"]:
                if conn["id"] == element_id:
                    for v, i in zip(values, ids):
                        key = i["prop"]
                        if conn["type"] == "MassFlowController" and key == "flow_rate":
                            try:
                                conn["properties"]["mass_flow_rate"] = float(v)
                            except Exception:
                                conn["properties"]["mass_flow_rate"] = v
                            if "flow_rate" in conn["properties"]:
                                del conn["properties"]["flow_rate"]
                        else:
                            conn["properties"][key] = v
                    break

        return config

    @app.callback(
        Output("last-selected-element", "data"),
        [Input("reactor-graph", "selectedNodeData"), Input("reactor-graph", "selectedEdgeData")],
        prevent_initial_call=True,
    )
    def update_last_selected(node_data, edge_data):
        if node_data:
            return {"type": "node", "data": node_data[0]}
        elif edge_data:
            return {"type": "edge", "data": edge_data[0]}
        return {} 