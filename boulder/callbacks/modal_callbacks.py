"""Callbacks for modal dialogs (reactor and MFC modals)."""

from typing import Any, Tuple, Union

import dash
import yaml
from dash import Input, Output, State, dcc


def register_callbacks(app) -> None:  # type: ignore
    """Register modal-related callbacks."""
    # ---- Add Component Modals ----

    @app.callback(
        Output("add-reactor-modal", "is_open"),
        [
            Input("open-reactor-modal", "n_clicks"),
            Input("close-reactor-modal", "n_clicks"),
        ],
        State("add-reactor-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_reactor_modal(n_open: int, n_close: int, is_open: bool) -> bool:
        if n_open or n_close:
            return not is_open
        return is_open

    @app.callback(
        Output("add-mfc-modal", "is_open"),
        [Input("open-mfc-modal", "n_clicks"), Input("close-mfc-modal", "n_clicks")],
        State("add-mfc-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_mfc_modal(n_open: int, n_close: int, is_open: bool) -> bool:
        if n_open or n_close:
            return not is_open
        return is_open

    # ---- Form Logic ----

    @app.callback(
        [Output("mfc-source", "options"), Output("mfc-target", "options")],
        Input("current-config", "data"),
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
            for comp in config.get("components", [])
            if comp.get("type") in valid_types
        ]
        return options, options

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

    # ---- Config Editor Modal ----

    @app.callback(
        [
            Output("config-yaml-modal", "is_open", allow_duplicate=True),
            Output("config-yaml-modal-body", "children"),
        ],
        Input("config-file-name-span", "n_clicks"),
        State("current-config", "data"),
        prevent_initial_call=True,
    )
    def open_config_yaml_modal(n_clicks: int, config: dict) -> Tuple[bool, Any]:
        """Open the YAML config modal, always in edit mode."""
        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        try:
            from ..config import convert_to_stone_format

            stone_config = convert_to_stone_format(config)
            yaml_str = yaml.dump(stone_config, sort_keys=False, indent=2)
            textarea = dcc.Textarea(
                id="config-yaml-editor",
                value=yaml_str,
                style={"width": "100%", "height": 400, "fontFamily": "monospace"},
            )
            return True, textarea
        except Exception as e:
            print(f"Error creating YAML for modal: {e}")
            return False, f"Error creating YAML: {e}"

    @app.callback(
        Output("config-yaml-modal", "is_open", allow_duplicate=True),
        Input("close-config-yaml-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_config_yaml_modal(n_clicks: int) -> bool:
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        return False

    @app.callback(
        [
            Output("current-config", "data", allow_duplicate=True),
            Output("config-yaml-modal", "is_open", allow_duplicate=True),
        ],
        Input("save-config-yaml-edit-btn", "n_clicks"),
        State("config-yaml-editor", "value"),
        prevent_initial_call=True,
    )
    def update_config_from_yaml(n_clicks: int, yaml_str: str) -> Tuple[dict, bool]:
        """Save changes from the YAML editor to the main config and close modal."""
        if not n_clicks or not yaml_str:
            raise dash.exceptions.PreventUpdate

        try:
            from ..config import normalize_config

            new_config = yaml.safe_load(yaml_str)
            normalized_config = normalize_config(new_config)
            return normalized_config, False
        except yaml.YAMLError as e:
            print(f"YAML Error on save: {e}")
            # In a real app, you'd show an error to the user here
            raise dash.exceptions.PreventUpdate
        except Exception as e:
            print(f"Error updating config from YAML: {e}")
            raise dash.exceptions.PreventUpdate

    @app.callback(
        Output("download-config-yaml", "data"),
        Input("save-config-yaml-btn", "n_clicks"),
        State("config-yaml-editor", "value"),
        prevent_initial_call=True,
    )
    def download_config_yaml(n_clicks: int, yaml_str: str) -> dict:
        """Download the current content of the YAML editor as a file."""
        if not n_clicks or not yaml_str:
            raise dash.exceptions.PreventUpdate

        return dict(content=yaml_str, filename="config.yaml")

    # ---- Auto-generate default IDs and values ----

    @app.callback(
        Output("reactor-id", "value"),
        Input("add-reactor-modal", "is_open"),
        State("current-config", "data"),
        prevent_initial_call=True,
    )
    def generate_reactor_id(is_open: bool, config: dict) -> Union[str, Any]:
        if not is_open:
            return dash.no_update

        existing_ids = [comp.get("id", "") for comp in config.get("components", [])]

        i = 1
        while f"reactor_{i}" in existing_ids:
            i += 1
        return f"reactor_{i}"

    @app.callback(
        Output("reactor-type", "value"),
        Input("add-reactor-modal", "is_open"),
        prevent_initial_call=True,
    )
    def set__default_reactor_type(is_open: bool) -> Union[str, Any]:
        if is_open:
            return "IdealGasReactor"
        return dash.no_update

    @app.callback(
        Output("mfc-id", "value"),
        Input("add-mfc-modal", "is_open"),
        State("current-config", "data"),
        prevent_initial_call=True,
    )
    def generate_mfc_id(is_open: bool, config: dict) -> Union[str, Any]:
        if not is_open:
            return dash.no_update

        existing_ids = [conn.get("id", "") for conn in config.get("connections", [])]
        i = 1
        while f"mfc_{i}" in existing_ids:
            i += 1
        return f"mfc_{i}"

    @app.callback(
        [
            Output("mfc-flow-rate", "value"),
            Output("mfc-source", "value"),
            Output("mfc-target", "value"),
        ],
        Input("add-mfc-modal", "is_open"),
        State("current-config", "data"),
        prevent_initial_call=True,
    )
    def set_default_mfc_values(is_open: bool, config: dict) -> tuple:
        if not is_open:
            return dash.no_update, dash.no_update, dash.no_update

        reactor_ids = [
            comp.get("id")
            for comp in config.get("components", [])
            if comp.get("type")
            in ["IdealGasReactor", "ConstVolReactor", "ConstPReactor", "Reservoir"]
        ]

        default_source = reactor_ids[0] if reactor_ids else None
        default_target = reactor_ids[1] if len(reactor_ids) > 1 else None

        return 0.001, default_source, default_target
