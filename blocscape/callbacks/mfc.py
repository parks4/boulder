from dash import Input, Output, State, callback_context
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc

def register_mfc_callbacks(app):
    @app.callback(
        Output("add-mfc-modal", "is_open"),
        [Input("open-mfc-modal", "n_clicks"), Input("close-mfc-modal", "n_clicks"), Input("add-mfc", "n_clicks")],
        [State("add-mfc-modal", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_mfc_modal(open_n, close_n, add_n, is_open):
        ctx = dash.callback_context
        if not ctx.triggered:
            return is_open
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "open-mfc-modal" and open_n:
            return True
        elif trigger in ("close-mfc-modal", "add-mfc") and (close_n or add_n):
            return False
        return is_open

    @app.callback(
        Output("add-mfc", "disabled"),
        [Input("mfc-id", "value"), Input("mfc-source", "value"), Input("mfc-target", "value")],
    )
    def enable_add_mfc_button(mfc_id, source, target):
        return not (mfc_id and source and target)

    @app.callback(
        Output("mfc-source", "options"),
        Output("mfc-target", "options"),
        [Input("current-config", "data")],
    )
    def update_reactor_options(config):
        options = [{"label": comp["id"], "value": comp["id"]} for comp in config["components"]]
        return options, options

    @app.callback(
        Output("mfc-id", "value", allow_duplicate=True),
        [Input("open-mfc-modal", "n_clicks"), Input("mfc-source", "value"), Input("mfc-target", "value"), Input("current-config", "data")],
        prevent_initial_call=True,
    )
    def auto_generate_mfc_id(open_n, source, target, config):
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
            
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "open-mfc-modal" and not open_n:
            raise dash.exceptions.PreventUpdate

        # If source and target are selected, use them in the ID
        if source and target:
            base_name = f"mfc_{source}_{target}"
        else:
            base_name = "mfc"

        # Find the next available number
        existing_ids = [conn["id"] for conn in config["connections"] if conn["id"].startswith(base_name)]
        if not existing_ids:
            return f"{base_name}1"
        
        # Extract numbers from existing IDs and find the next one
        numbers = []
        for id_str in existing_ids:
            try:
                num = int(id_str[len(base_name):])
                numbers.append(num)
            except ValueError:
                continue
        
        next_num = max(numbers, default=0) + 1
        return f"{base_name}{next_num}"

    @app.callback(
        Output("current-config", "data", allow_duplicate=True),
        [Input("add-mfc", "n_clicks")],
        [
            State("mfc-id", "value"),
            State("mfc-flow-rate", "value"),
            State("mfc-source", "value"),
            State("mfc-target", "value"),
            State("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def add_mfc(n_clicks, mfc_id, flow_rate, source, target, config):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        # Check if MFC ID already exists
        for conn in config["connections"]:
            if conn["id"] == mfc_id:
                return config

        # Add new MFC
        new_mfc = {
            "id": mfc_id,
            "type": "MassFlowController",
            "source": source,
            "target": target,
            "properties": {
                "mass_flow_rate": flow_rate,
            },
        }
        config["connections"].append(new_mfc)
        return config

    @app.callback(
        [
            Output("mfc-id", "value", allow_duplicate=True),
            Output("mfc-flow-rate", "value", allow_duplicate=True),
            Output("mfc-source", "value", allow_duplicate=True),
            Output("mfc-target", "value", allow_duplicate=True),
        ],
        [Input("add-mfc", "n_clicks")],
        prevent_initial_call=True,
    )
    def clear_mfc_form(n_clicks):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        return "", 0.001, None, None  # Reset to default values 