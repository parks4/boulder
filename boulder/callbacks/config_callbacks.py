"""Callbacks for configuration file handling and YAML editing."""

import base64

import dash
import yaml
from dash import Input, Output, State, dcc, html

# Configure YAML to preserve dict order without Python tags
yaml.add_representer(
    dict,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map", data.items()
    ),
)


def convert_to_stone_format(config: dict) -> dict:
    """Convert internal format back to YAML with 🪨 STONE standard for file saving."""
    stone_config = {}

    # Copy metadata and simulation sections as-is
    if "metadata" in config:
        stone_config["metadata"] = config["metadata"]
    if "simulation" in config:
        stone_config["simulation"] = config["simulation"]

    # Convert components
    if "components" in config:
        stone_config["components"] = []
        for component in config["components"]:
            # Build component with id first, then type
            component_type = component.get("type", "IdealGasReactor")
            stone_component = {
                "id": component["id"],
                component_type: component.get("properties", {}),
            }
            stone_config["components"].append(stone_component)

    # Convert connections
    if "connections" in config:
        stone_config["connections"] = []
        for connection in config["connections"]:
            # Build connection with id first, then type, then source/target
            connection_type = connection.get("type", "MassFlowController")
            stone_connection = {
                "id": connection["id"],
                connection_type: connection.get("properties", {}),
                "source": connection["source"],
                "target": connection["target"],
            }
            stone_config["connections"].append(stone_connection)

    return stone_config


def register_callbacks(app) -> None:  # type: ignore
    """Register config-related callbacks."""

    # Callback to render the config upload area
    @app.callback(
        Output("config-upload-area", "children"),
        [Input("config-file-name", "data")],
    )
    def render_config_upload_area(file_name: str) -> tuple:
        if file_name:
            return (
                html.Div(
                    [
                        dcc.Upload(
                            id="upload-config",
                            style={"display": "none"},  # Always present, just hidden
                        ),
                        html.Span(
                            file_name,
                            id="config-file-name-span",
                            style={
                                "cursor": "pointer",
                                "fontWeight": "bold",
                                "marginRight": 10,
                            },
                            n_clicks=0,
                        ),
                        html.Button(
                            "✕",
                            id="delete-config-file",
                            n_clicks=0,
                            style={
                                "color": "red",
                                "border": "none",
                                "background": "none",
                                "fontSize": 18,
                                "cursor": "pointer",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "marginBottom": 10,
                    },
                ),
            )
        else:
            return (
                dcc.Upload(
                    id="upload-config",
                    children=html.Div(["Drop or ", html.A("Select Config File")]),
                    style={
                        "width": "100%",
                        "height": "60px",
                        "lineHeight": "60px",
                        "borderWidth": "1px",
                        "borderStyle": "dashed",
                        "borderRadius": "5px",
                        "textAlign": "center",
                        "margin": "10px 0",
                    },
                    multiple=False,
                ),
            )

    # Callback to handle config upload and delete
    @app.callback(
        [
            Output("current-config", "data"),
            Output("config-file-name", "data"),
        ],
        [
            Input("upload-config", "contents"),
            Input("delete-config-file", "n_clicks"),
        ],
        [
            State("upload-config", "filename"),
        ],
        prevent_initial_call=True,
    )
    def handle_config_upload_delete(
        upload_contents: str,
        delete_n_clicks: int,
        upload_filename: str,
    ) -> tuple:
        from ..config import get_initial_config

        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "upload-config" and upload_contents:
            content_type, content_string = upload_contents.split(",")
            try:
                decoded_string = base64.b64decode(content_string).decode("utf-8")
                # Only accept YAML files with 🪨 STONE standard
                if upload_filename and upload_filename.lower().endswith(
                    (".yaml", ".yml")
                ):
                    from ..config import normalize_config

                    decoded = yaml.safe_load(decoded_string)
                    # Normalize from YAML with 🪨 STONE standard to internal format
                    normalized = normalize_config(decoded)
                    return normalized, upload_filename
                else:
                    print(
                        "Only YAML format with 🪨 STONE standard (.yaml/.yml) files are supported. Got:"
                        f" {upload_filename}"
                    )
                    return dash.no_update, ""
            except Exception as e:
                print(f"Error processing uploaded file: {e}")
                return dash.no_update, ""
        elif trigger == "delete-config-file" and delete_n_clicks:
            return get_initial_config(), ""
        else:
            raise dash.exceptions.PreventUpdate

    # Separate callback to handle config YAML edit save
    @app.callback(
        Output("current-config", "data", allow_duplicate=True),
        [Input("save-config-yaml-edit-btn", "n_clicks")],
        [
            State("config-yaml-edit-textarea", "value"),
            State("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_config_yaml_edit_save(
        save_edit_n_clicks: int,
        edit_text: str,
        old_config: dict,
    ) -> dict:
        if save_edit_n_clicks:
            try:
                from ..config import normalize_config

                # Parse YAML with 🪨 STONE standard
                parsed_config = yaml.safe_load(edit_text)
                # Normalize to internal format
                new_config = normalize_config(parsed_config)
                return new_config
            except Exception:
                return old_config
        raise dash.exceptions.PreventUpdate

    # Callback to render the modal body (view or edit mode)
    @app.callback(
        Output("config-yaml-modal-body", "children"),
        [Input("config-yaml-edit-mode", "data"), Input("current-config", "data")],
    )
    def render_config_yaml_modal_body(edit_mode: bool, config: dict) -> tuple:
        if edit_mode:
            # Convert internal format to YAML with 🪨 STONE standard for editing
            stone_config = convert_to_stone_format(config)
            yaml_content = yaml.dump(
                stone_config, default_flow_style=False, indent=2, sort_keys=False
            )
            return (
                html.Div(
                    [
                        dcc.Textarea(
                            id="config-yaml-edit-textarea",
                            value=yaml_content,
                            style={
                                "width": "100%",
                                "height": "60vh",
                                "fontFamily": "monospace",
                            },
                        ),
                    ]
                ),
            )
        else:
            # Convert internal format to YAML with 🪨 STONE standard for viewing
            stone_config = convert_to_stone_format(config)
            yaml_content = yaml.dump(
                stone_config, default_flow_style=False, indent=2, sort_keys=False
            )
            return (
                html.Pre(
                    yaml_content,
                    style={"maxHeight": "60vh", "overflowY": "auto"},
                ),
            )

    # Callback to handle edit mode switching
    @app.callback(
        Output("config-yaml-edit-mode", "data"),
        [
            Input("edit-config-yaml-btn", "n_clicks"),
            Input("cancel-config-yaml-edit-btn", "n_clicks"),
            Input("save-config-yaml-edit-btn", "n_clicks"),
            Input("close-config-yaml-modal", "n_clicks"),
        ],
        [State("config-yaml-edit-mode", "data")],
        prevent_initial_call=True,
    )
    def toggle_config_yaml_edit_mode(
        edit_n: int,
        cancel_n: int,
        save_n: int,
        close_n: int,
        edit_mode: bool,
    ) -> bool:
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "edit-config-yaml-btn":
            return True
        elif trigger in (
            "cancel-config-yaml-edit-btn",
            "save-config-yaml-edit-btn",
            "close-config-yaml-modal",
        ):
            return False
        return edit_mode

    # Callback to download config as YAML with 🪨 STONE standard
    @app.callback(
        Output("download-config-yaml", "data"),
        [Input("save-config-yaml-btn", "n_clicks")],
        [State("current-config", "data")],
        prevent_initial_call=True,
    )
    def download_config_stone(n: int, config: dict):
        if n:
            # Convert from internal format back to YAML with 🪨 STONE standard
            stone_config = convert_to_stone_format(config)
            yaml_content = yaml.dump(
                stone_config, default_flow_style=False, indent=2, sort_keys=False
            )
            return dict(content=yaml_content, filename="config.yaml")
        return dash.no_update

    @app.callback(
        Output("config-yaml-modal", "is_open"),
        [
            Input("config-file-name-span", "n_clicks"),
            Input("close-config-yaml-modal", "n_clicks"),
        ],
        [State("config-yaml-modal", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_config_yaml_modal(open_n: int, close_n: int, is_open: bool) -> bool:
        """Toggle the configuration YAML modal."""
        ctx = dash.callback_context
        if not ctx.triggered:
            return is_open
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "config-file-name-span" and open_n:
            return True
        elif trigger == "close-config-yaml-modal" and close_n:
            return False
        return is_open

    # Add a callback to control button visibility
    @app.callback(
        [
            Output("save-config-yaml-btn", "style"),
            Output("edit-config-yaml-btn", "style"),
            Output("save-config-yaml-edit-btn", "style"),
            Output("cancel-config-yaml-edit-btn", "style"),
            Output("close-config-yaml-modal", "style"),
        ],
        [Input("config-yaml-edit-mode", "data")],
    )
    def set_yaml_modal_button_visibility(edit_mode: bool):
        if edit_mode:
            return (
                {"display": "none"},
                {"display": "none"},
                {"display": "block"},
                {"display": "block"},
                {"display": "none"},
            )
        else:
            return (
                {"display": "block"},
                {"display": "block"},
                {"display": "none"},
                {"display": "none"},
                {"display": "block"},
            )
