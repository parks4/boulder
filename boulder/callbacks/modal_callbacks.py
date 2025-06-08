"""Callbacks for modal dialogs (reactor and MFC modals)."""

from typing import Any, Union

import dash
from dash import Input, Output, State


def register_callbacks(app) -> None:  # type: ignore
    """Register modal-related callbacks."""

    # Callback to open/close Reactor modal
    @app.callback(
        Output("add-reactor-modal", "is_open"),
        [
            Input("open-reactor-modal", "n_clicks"),
            Input("close-reactor-modal", "n_clicks"),
            Input("add-reactor", "n_clicks"),
        ],
        [State("add-reactor-modal", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_reactor_modal(n1: int, n2: int, n3: int, is_open: bool) -> bool:
        ctx = dash.callback_context
        if not ctx.triggered:
            return is_open
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "open-reactor-modal" and n1:
            return True
        elif trigger == "close-reactor-modal" and n2:
            return False
        elif trigger == "add-reactor" and n3:
            return False
        return is_open

    # Callback to open/close MFC modal
    @app.callback(
        Output("add-mfc-modal", "is_open"),
        [
            Input("open-mfc-modal", "n_clicks"),
            Input("close-mfc-modal", "n_clicks"),
            Input("add-mfc", "n_clicks"),
        ],
        [State("add-mfc-modal", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_mfc_modal(n1: int, n2: int, n3: int, is_open: bool) -> bool:
        ctx = dash.callback_context
        if not ctx.triggered:
            return is_open
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "open-mfc-modal" and n1:
            return True
        elif trigger == "close-mfc-modal" and n2:
            return False
        elif trigger == "add-mfc" and n3:
            return False
        return is_open

    # Callback to update MFC source/target options
    @app.callback(
        [Output("mfc-source", "options"), Output("mfc-target", "options")],
        [Input("current-config", "data")],
    )
    def update_mfc_options(config: dict) -> tuple[list[dict], list[dict]]:
        valid_types = [
            "IdealGasReactor",
            "ConstVolReactor",
            "ConstPReactor",
            "Reservoir",
        ]
        options = [
            {"label": comp["id"], "value": comp["id"]}
            for comp in config["components"]
            if comp["type"] in valid_types
        ]
        return options, options

    # Add callbacks to enable/disable Add buttons based on form fields
    @app.callback(
        Output("add-reactor", "disabled"),
        [
            Input("reactor-id", "value"),
            Input("reactor-type", "value"),
            Input("reactor-temp", "value"),
            Input("reactor-pressure", "value"),
        ],
    )
    def toggle_reactor_button(
        reactor_id: str, reactor_type: str, temp: float, pressure: float
    ) -> bool:
        return not all([reactor_id, reactor_type, temp, pressure])

    @app.callback(
        Output("add-mfc", "disabled"),
        [
            Input("mfc-id", "value"),
            Input("mfc-source", "value"),
            Input("mfc-target", "value"),
            Input("mfc-flow-rate", "value"),
        ],
    )
    def toggle_mfc_button(
        mfc_id: str, source: str, target: str, flow_rate: float
    ) -> bool:
        return not all([mfc_id, source, target, flow_rate])

    # Auto-generate default IDs and values
    @app.callback(
        Output("reactor-id", "value"),
        [Input("add-reactor-modal", "is_open")],
        [State("current-config", "data")],
        prevent_initial_call=True,
    )
    def generate_reactor_id(is_open: bool, config: dict) -> Union[str, Any]:
        if not is_open:
            return dash.no_update

        existing_ids = [
            comp["id"]
            for comp in config["components"]
            if comp["type"] in ["IdealGasReactor", "ConstVolReactor", "ConstPReactor"]
        ]

        max_num = 0
        for id in existing_ids:
            if id.startswith("reactor_"):
                try:
                    num = int(id.split("_")[1])
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    continue

        return f"reactor_{max_num + 1}"

    @app.callback(
        Output("reactor-type", "value"),
        [Input("add-reactor-modal", "is_open")],
        prevent_initial_call=True,
    )
    def set_default_reactor_type(is_open: bool) -> Union[str, Any]:
        if is_open:
            return "IdealGasReactor"
        return dash.no_update

    @app.callback(
        Output("mfc-id", "value"),
        [Input("add-mfc-modal", "is_open")],
        [State("current-config", "data")],
        prevent_initial_call=True,
    )
    def generate_mfc_id(is_open: bool, config: dict) -> Union[str, Any]:
        if not is_open:
            return dash.no_update

        existing_ids = [
            comp["id"]
            for comp in config["components"]
            if comp["type"] == "MassFlowController"
        ]

        max_num = 0
        for id in existing_ids:
            if id.startswith("mfc_"):
                try:
                    num = int(id.split("_")[1])
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    continue

        return f"mfc_{max_num + 1}"

    @app.callback(
        [
            Output("mfc-flow-rate", "value"),
            Output("mfc-source", "value"),
            Output("mfc-target", "value"),
        ],
        [Input("add-mfc-modal", "is_open")],
        [State("current-config", "data")],
        prevent_initial_call=True,
    )
    def set_default_mfc_values(is_open: bool, config: dict) -> tuple:
        if not is_open:
            return dash.no_update, dash.no_update, dash.no_update

        reactor_ids = [
            comp["id"]
            for comp in config["components"]
            if comp["type"] in ["IdealGasReactor", "ConstVolReactor", "ConstPReactor"]
        ]

        default_source = reactor_ids[0] if reactor_ids else None
        default_target = reactor_ids[1] if len(reactor_ids) > 1 else None

        return 0.001, default_source, default_target
