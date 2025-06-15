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

    # The toggle_config_yaml_edit_mode callback is being removed as the modal
    # now always opens in edit mode, making this logic obsolete.
