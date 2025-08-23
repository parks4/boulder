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
                    # Handle both Python and YAML files with unified logic
                    import os
                    import tempfile

                    from ..config import (
                        load_config_file_with_py_support_and_comments,
                        load_yaml_string_with_comments,
                        normalize_config,
                        validate_config,
                    )

                    if upload_filename.lower().endswith(".py"):
                        # Step 1: Save Python file to temporary location
                        with tempfile.NamedTemporaryFile(
                            mode="w", suffix=".py", delete=False, encoding="utf-8"
                        ) as temp_file:
                            temp_file.write(decoded_string)
                            temp_py_path = temp_file.name

                        try:
                            # Step 2: Convert Python to YAML, then load the YAML
                            config, original_yaml, actual_yaml_path = (
                                load_config_file_with_py_support_and_comments(
                                    temp_py_path, verbose=is_verbose_mode()
                                )
                            )
                            normalized = normalize_config(config)
                            validated = validate_config(normalized)

                            if is_verbose_mode():
                                logger.info(
                                    f"Successfully converted Python to YAML and loaded: {upload_filename}"
                                )

                            # Use the original filename for display, but note it was converted
                            display_filename = f"{upload_filename} (converted to YAML)"
                            return (
                                validated,
                                display_filename,
                                original_yaml,
                                dash.no_update,
                            )

                        finally:
                            # Clean up temporary file
                            if os.path.exists(temp_py_path):
                                os.unlink(temp_py_path)
                    else:
                        # Step 1 & 2: For YAML files, load directly (no conversion needed)
                        # Use comment-preserving YAML loader with fallback
                        try:
                            decoded = load_yaml_string_with_comments(decoded_string)
                        except (yaml.YAMLError, AttributeError):
                            # Fallback to standard loader for compatibility
                            decoded = yaml.safe_load(decoded_string)

                        # Normalize from YAML with 🪨 STONE standard to internal format
                        normalized = normalize_config(decoded)
                        # Validate the configuration (this will also convert units)
                        normalized = validate_config(normalized)
                        if is_verbose_mode():
                            logger.info(
                                f"Successfully loaded YAML file: {upload_filename}"
                            )
                        return (
                            normalized,
                            upload_filename,
                            decoded_string,
                            dash.no_update,
                        )
                else:
                    print(
                        "Only YAML format with 🪨 STONE standard (.yaml/.yml) and Python (.py) files are supported. Got:"
                        f" {upload_filename}"
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
