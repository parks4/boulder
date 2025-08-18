"""Callbacks for toast notifications."""

import base64

import dash
from dash import Input, Output, State

from ..verbose_utils import get_verbose_logger, is_verbose_mode

logger = get_verbose_logger(__name__)


def register_callbacks(app) -> None:  # type: ignore
    """Register notification-related callbacks."""

    @app.callback(
        [
            Output("notification-toast", "is_open"),
            Output("notification-toast", "children"),
            Output("notification-toast", "header"),
            Output("notification-toast", "icon"),
        ],
        [
            Input("upload-config", "contents"),
            Input("delete-config-file", "n_clicks"),
            Input("save-config-yaml-edit-btn", "n_clicks"),
            Input("run-simulation", "n_clicks"),
        ],
        [
            State("upload-config", "filename"),
            State("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def notification_handler(
        upload_contents: str,
        delete_config_click: int,
        save_edit_click: int,
        run_sim_click: int,
        upload_filename: str,
        config: dict,
    ):
        """Handle the various events that can trigger the notification toast."""
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

        # Config upload
        if trigger == "upload-config" and upload_contents:
            if is_verbose_mode():
                logger.info(f"Processing uploaded config file: {upload_filename}")
            try:
                import yaml

                content_type, content_string = upload_contents.split(",")
                decoded_string = base64.b64decode(content_string).decode("utf-8")

                if is_verbose_mode():
                    logger.info(
                        f"File content preview (first 200 chars): {decoded_string[:200]}..."
                    )

                # Validate as YAML (STONE standard) instead of JSON
                parsed_yaml = yaml.safe_load(decoded_string)

                if is_verbose_mode():
                    keys_info = (
                        list(parsed_yaml.keys())
                        if isinstance(parsed_yaml, dict)
                        else "Not a dict"
                    )
                    logger.info(f"YAML parsed successfully. Keys: {keys_info}")

                return (
                    True,
                    f"✅ Configuration loaded from {upload_filename}",
                    "Success",
                    "success",
                )
            except Exception as e:
                message = f"Could not parse file {upload_filename}. Error: {e}"
                if is_verbose_mode():
                    logger.error(
                        f"File upload failed for {upload_filename}: {message}",
                        exc_info=True,
                    )
                else:
                    print(f"ERROR: {message}")
                return (
                    True,
                    message,
                    "Error",
                    "danger",
                )

        # Config delete
        if trigger == "delete-config-file" and delete_config_click:
            return True, "Config file removed.", "Success", "success"

        # Config edit
        if trigger == "save-config-yaml-edit-btn" and save_edit_click:
            return (
                True,
                "✅ Configuration updated from editor.",
                "Success",
                "success",
            )

        # Run simulation: suppress success notification in normal mode
        if trigger == "run-simulation" and run_sim_click:
            return False, "", "", dash.no_update

        return False, "", "", "primary"
