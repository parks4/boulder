"""Callbacks for configuration file handling and YAML editing."""

import base64

import dash
import yaml
from dash import Input, Output, State, dcc, html

from ..verbose_utils import get_verbose_logger, is_verbose_mode

logger = get_verbose_logger(__name__)

# Configure YAML to preserve dict order without Python tags
yaml.add_representer(
    dict,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map", data.items()
    ),
)


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
                html.Div(
                    [
                        dcc.Upload(
                            id="upload-config",
                            children=html.Div(
                                ["Drop or ", html.A("Select Config File")]
                            ),
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
                        # Always include delete button but hide it when no file is loaded
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
                                "display": "none",  # Hidden when no file is loaded
                            },
                        ),
                    ]
                ),
            )

    # Callback to handle config upload and delete
    @app.callback(
        [
            Output("current-config", "data"),
            Output("config-file-name", "data"),
            Output("original-yaml-with-comments", "data"),
            Output("upload-config", "contents"),  # Add this to reset upload contents
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
                # Accept YAML files with 🪨 STONE standard and Python files
                if upload_filename and upload_filename.lower().endswith(
                    (".yaml", ".yml", ".py")
                ):
                    import os
                    import tempfile

                    from ..config import (
                        load_yaml_string_with_comments,
                        normalize_config,
                        validate_config,
                    )

                    # Step 0: Convert Python to YAML if needed (preliminary conversion step)
                    yaml_content = decoded_string
                    display_filename = upload_filename
                    cleanup_files = []

                    if upload_filename.lower().endswith(".py"):
                        from ..parser import convert_py_to_yaml

                        # Create a temporary output path for the YAML
                        with tempfile.NamedTemporaryFile(
                            suffix=".yaml", delete=False
                        ) as temp_yaml:
                            temp_yaml_path = temp_yaml.name
                        cleanup_files.append(temp_yaml_path)

                        # Convert Python content to YAML
                        yaml_path = convert_py_to_yaml(
                            decoded_string,
                            output_path=temp_yaml_path,
                            verbose=is_verbose_mode(),
                        )

                        # Read the converted YAML content
                        with open(yaml_path, "r", encoding="utf-8") as f:
                            yaml_content = f.read()

                        # Update display filename to show conversion
                        display_filename = f"{upload_filename} (converted to YAML)"

                        if is_verbose_mode():
                            logger.info(
                                f"Python file converted to YAML: {upload_filename}"
                            )

                    try:
                        # Step 1 & 2: Common YAML processing pipeline
                        # (for both original YAML and converted Python)
                        # Use comment-preserving YAML loader with fallback
                        try:
                            decoded = load_yaml_string_with_comments(yaml_content)
                        except (yaml.YAMLError, AttributeError):
                            # Fallback to standard loader for compatibility
                            decoded = yaml.safe_load(yaml_content)

                        # Normalize from YAML with 🪨 STONE standard to internal format
                        normalized = normalize_config(decoded)
                        # Validate the configuration (this will also convert units)
                        validated = validate_config(normalized)

                        if is_verbose_mode():
                            logger.info(
                                f"Successfully loaded configuration: {display_filename}"
                            )

                        return (
                            validated,
                            display_filename,
                            yaml_content,
                            dash.no_update,
                        )

                    finally:
                        # Clean up any temporary files
                        for cleanup_file in cleanup_files:
                            if os.path.exists(cleanup_file):
                                os.unlink(cleanup_file)
                else:
                    print(
                        "Only YAML format with 🪨 STONE standard (.yaml/.yml) and "
                        f"Python (.py) files are supported. Got: {upload_filename}"
                    )
                    return dash.no_update, "", "", dash.no_update
            except Exception as e:
                if is_verbose_mode():
                    logger.error(f"Error processing uploaded file: {e}", exc_info=True)
                else:
                    print(f"Error processing uploaded file: {e}")
                return dash.no_update, "", "", dash.no_update
        elif trigger == "delete-config-file" and delete_n_clicks:
            return get_initial_config(), "", "", None  # Reset upload contents to None
        else:
            raise dash.exceptions.PreventUpdate

    # The toggle_config_yaml_edit_mode callback is being removed as the modal
    # now always opens in edit mode, making this logic obsolete.
