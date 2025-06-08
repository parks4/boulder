from dash import Input, Output, State, callback_context, no_update
import dash
import base64
import json
from dash import html, dcc
import dash_bootstrap_components as dbc
import os

# You may need to import initial_config from layout or define it here
from ..layout import initial_config

def register_config_callbacks(app):
    @app.callback(
        [
            Output("current-config", "data"),
            Output("config-file-name", "data"),
            Output("notification-toast", "is_open", allow_duplicate=True),
            Output("notification-toast", "children", allow_duplicate=True),
            Output("notification-toast", "header", allow_duplicate=True),
        ],
        [Input("upload-config", "contents"), Input("save-config-json-edit-btn", "n_clicks")],
        [State("upload-config", "filename"), State("config-json-edit-textarea", "value"), State("current-config", "data")],
        prevent_initial_call=True,
    )
    def handle_config_all(upload_contents, save_edit_n_clicks, upload_filename, edit_text, old_config):
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        
        if trigger == "upload-config" and upload_contents:
            content_type, content_string = upload_contents.split(",")
            try:
                decoded_string = base64.b64decode(content_string).decode("utf-8")
                decoded = json.loads(decoded_string)
                return decoded, upload_filename, True, f"Successfully loaded {upload_filename}", "Success"
            except json.JSONDecodeError as e:
                return old_config, "", True, f"Invalid JSON format: {str(e)}", "Error"
            except Exception as e:
                return old_config, "", True, f"Error loading file: {str(e)}", "Error"
            
        elif trigger == "save-config-json-edit-btn" and save_edit_n_clicks:
            try:
                new_config = json.loads(edit_text)
                return new_config, no_update, True, "Configuration saved successfully", "Success"
            except json.JSONDecodeError as e:
                return old_config, no_update, True, f"Invalid JSON format: {str(e)}", "Error"
            except Exception as e:
                return old_config, no_update, True, f"Error saving configuration: {str(e)}", "Error"
                
        raise dash.exceptions.PreventUpdate

    @app.callback(
        [
            Output("current-config", "data", allow_duplicate=True),
            Output("config-file-name", "data", allow_duplicate=True),
            Output("notification-toast", "is_open", allow_duplicate=True),
            Output("notification-toast", "children", allow_duplicate=True),
            Output("notification-toast", "header", allow_duplicate=True),
        ],
        [Input("config-upload-area", "n_clicks")],
        [State("config-file-name", "data")],
        prevent_initial_call=True,
    )
    def reset_config(n_clicks, current_filename):
        if not n_clicks or not current_filename:
            raise dash.exceptions.PreventUpdate
        return initial_config, "", True, "Configuration reset to default", "Success"

    @app.callback(
        Output("config-upload-area", "children"),
        [Input("config-file-name", "data")],
    )
    def render_config_upload_area(file_name):
        if file_name:
            return html.Div(
                [
                    dcc.Upload(
                        id="upload-config",
                        style={"display": "none"},
                    ),
                    html.Div(
                        [
                            html.Span(
                                file_name,
                                style={
                                    "fontWeight": "bold",
                                    "marginRight": 10,
                                    "color": "#666",
                                },
                            ),
                            html.Span(
                                "✕",
                                style={
                                    "color": "red",
                                    "cursor": "pointer",
                                    "fontSize": 18,
                                    "padding": "0 5px",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "marginBottom": 10,
                            "padding": "5px",
                            "border": "1px solid #ddd",
                            "borderRadius": "5px",
                        },
                        id="config-upload-area",
                        n_clicks=0,
                    ),
                ],
            )
        else:
            return dcc.Upload(
                id="upload-config",
                children=html.Div(
                    [
                        "Drop or ",
                        html.A("Select Config File", style={"color": "#007bff"}),
                    ],
                    style={"color": "#666"},
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
                    "backgroundColor": "#f8f9fa",
                },
                multiple=False,
            )

    @app.callback(
        Output("config-json-modal-body", "children"),
        [Input("config-json-edit-mode", "data"), Input("current-config", "data")],
    )
    def render_config_json_modal_body(edit_mode, config):
        if edit_mode:
            return (
                html.Div([
                    dcc.Textarea(
                        id="config-json-edit-textarea",
                        value=json.dumps(config, indent=2),
                        style={"width": "100%", "height": "60vh", "fontFamily": "monospace"},
                    ),
                ]),
            )
        else:
            return (
                html.Pre(json.dumps(config, indent=2), style={"maxHeight": "60vh", "overflowY": "auto"}),
            )

    @app.callback(
        Output("config-json-edit-mode", "data"),
        [Input("edit-config-json-btn", "n_clicks")],
        [State("config-json-edit-mode", "data")],
        prevent_initial_call=True,
    )
    def toggle_config_json_edit_mode(n_clicks, current_mode):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        return not current_mode

    @app.callback(
        [
            Output("config-json-modal-body", "children", allow_duplicate=True),
            Output("config-json-edit-textarea", "value", allow_duplicate=True),
        ],
        [
            Input("config-json-modal", "is_open"),
            Input("current-config", "data"),
            Input("config-json-edit-mode", "data"),
        ],
        [State("config-json-edit-textarea", "value")],
        prevent_initial_call=True,
    )
    def update_config_json_modal(is_open, config, edit_mode, current_text):
        if not is_open:
            raise dash.exceptions.PreventUpdate

        if edit_mode:
            if not current_text:
                current_text = json.dumps(config, indent=2)
            return [
                dbc.Textarea(
                    id="config-json-edit-textarea",
                    value=current_text,
                    style={"height": "400px"},
                )
            ], current_text
        else:
            return [
                html.Pre(
                    json.dumps(config, indent=2),
                    style={"whiteSpace": "pre-wrap", "wordBreak": "break-all"},
                )
            ], ""

    @app.callback(
        [
            Output("current-config", "data", allow_duplicate=True),
            Output("config-json-edit-mode", "data", allow_duplicate=True),
            Output("notification-toast", "is_open", allow_duplicate=True),
            Output("notification-toast", "children", allow_duplicate=True),
            Output("notification-toast", "header", allow_duplicate=True),
        ],
        [Input("save-config-json-edit-btn", "n_clicks")],
        [State("config-json-edit-textarea", "value")],
        prevent_initial_call=True,
    )
    def save_config_json(n_clicks, json_text):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate

        try:
            new_config = json.loads(json_text)
            return new_config, False, True, "Configuration saved successfully!", "Success"
        except json.JSONDecodeError as e:
            return dash.no_update, dash.no_update, True, str(e), "Error"
        except Exception as e:
            return dash.no_update, dash.no_update, True, str(e), "Error"

    @app.callback(
        Output("download-config-json", "data"),
        [Input("save-config-json-btn", "n_clicks")],
        [State("current-config", "data")],
        prevent_initial_call=True,
    )
    def download_config_json(n, config):
        if n:
            return dict(content=json.dumps(config, indent=2), filename="config.json")
        return dash.no_update

    @app.callback(
        Output("config-json-modal", "is_open"),
        [Input("config-file-name-span", "n_clicks"), Input("close-config-json-modal", "n_clicks")],
        [State("config-json-modal", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_config_json_modal(open_n, close_n, is_open):
        ctx = dash.callback_context
        if not ctx.triggered:
            return is_open
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "config-file-name-span" and open_n:
            return True
        elif trigger == "close-config-json-modal" and close_n:
            return False
        return is_open

    @app.callback(
        [
            Output("save-config-json-btn", "style"),
            Output("edit-config-json-btn", "style"),
            Output("save-config-json-edit-btn", "style"),
            Output("cancel-config-json-edit-btn", "style"),
            Output("close-config-json-modal", "style"),
        ],
        [Input("config-json-edit-mode", "data")],
    )
    def set_json_modal_button_visibility(edit_mode):
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