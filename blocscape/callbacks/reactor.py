from dash import Input, Output, State, callback_context
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from ..layout import config_to_cyto_elements

def register_reactor_callbacks(app):
    @app.callback(
        Output("add-reactor-modal", "is_open"),
        [Input("open-reactor-modal", "n_clicks"), Input("close-reactor-modal", "n_clicks"), Input("add-reactor", "n_clicks")],
        [State("add-reactor-modal", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_reactor_modal(open_n, close_n, add_n, is_open):
        ctx = dash.callback_context
        if not ctx.triggered:
            return is_open
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "open-reactor-modal" and open_n:
            return True
        elif trigger in ("close-reactor-modal", "add-reactor") and (close_n or add_n):
            return False
        return is_open

    @app.callback(
        Output("add-reactor", "disabled"),
        [Input("reactor-id", "value")],
    )
    def enable_add_reactor_button(reactor_id):
        return not reactor_id

    @app.callback(
        Output("reactor-id", "value", allow_duplicate=True),
        [Input("reactor-type", "value"), Input("open-reactor-modal", "n_clicks"), Input("current-config", "data")],
        prevent_initial_call=True,
    )
    def auto_generate_reactor_id(reactor_type, open_n, config):
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
            
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "open-reactor-modal" and not open_n:
            raise dash.exceptions.PreventUpdate

        if not reactor_type:
            raise dash.exceptions.PreventUpdate

        # Get the base name from reactor type
        base_name = reactor_type.replace("Reactor", "").lower()
        if base_name == "idealgas":
            base_name = "igr"
        elif base_name == "idealgasconstpressure":
            base_name = "igcp"
        elif base_name == "idealgasconstvolume":
            base_name = "igcv"
        elif base_name == "constvol":
            base_name = "cv"
        elif base_name == "constp":
            base_name = "cp"
        elif base_name == "reservoir":
            base_name = "res"

        # Find the next available number
        existing_ids = [comp["id"] for comp in config["components"] if comp["id"].startswith(base_name)]
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
        [
            Output("reactor-temp", "value"),
            Output("reactor-pressure", "value"),
            Output("reactor-composition", "value"),
        ],
        [Input("reactor-type", "value")],
    )
    def update_reactor_form_defaults(reactor_type):
        if reactor_type == "Reservoir":
            return 300, 101325, "O2:1,N2:3.76"
        elif reactor_type == "Reactor":
            return 300, 101325, "O2:1,N2:3.76"
        elif reactor_type == "IdealGasReactor":
            return 300, 101325, "O2:1,N2:3.76"
        elif reactor_type == "IdealGasConstPressureReactor":
            return 300, 101325, "O2:1,N2:3.76"
        elif reactor_type == "IdealGasConstVolumeReactor":
            return 300, 101325, "O2:1,N2:3.76"
        return 300, 101325, "O2:1,N2:3.76"  # Default values

    @app.callback(
        Output("current-config", "data", allow_duplicate=True),
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
    def add_reactor(n_clicks, reactor_id, reactor_type, temp, pressure, composition, config):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        # Check if reactor ID already exists
        for comp in config["components"]:
            if comp["id"] == reactor_id:
                return config

        # Add new reactor
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
        return config

    @app.callback(
        [
            Output("reactor-id", "value", allow_duplicate=True),
            Output("reactor-temp", "value", allow_duplicate=True),
            Output("reactor-pressure", "value", allow_duplicate=True),
            Output("reactor-composition", "value", allow_duplicate=True),
        ],
        [Input("add-reactor", "n_clicks")],
        prevent_initial_call=True,
    )
    def clear_reactor_form(n_clicks):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        return "", 300, 101325, "O2:1,N2:3.76"  # Reset to default values

    @app.callback(
        Output("reactor-graph", "elements"),
        [Input("current-config", "data")],
    )
    def update_cytoscape_elements(config):
        return config_to_cyto_elements(config) 