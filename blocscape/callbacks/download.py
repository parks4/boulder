from dash import Input, Output, State, callback_context
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
import datetime

def register_download_callbacks(app):
    @app.callback(
        Output("download-python-code-btn-container", "children"),
        [Input("last-sim-python-code", "data")],
    )
    def show_download_button(code):
        if not code:
            return []
        return [
            dbc.Button(
                "Download .py",
                id="download-python-code",
                color="primary",
                className="w-100",
            ),
            dcc.Download(id="download-python-code-file"),
        ]

    @app.callback(
        Output("download-python-code-file", "data"),
        [Input("download-python-code", "n_clicks")],
        [State("last-sim-python-code", "data"), State("config-file-name", "data")],
        prevent_initial_call=True,
    )
    def download_python_code(n_clicks, code, config_filename):
        if not n_clicks or not code:
            raise dash.exceptions.PreventUpdate

        # Generate filename based on config file or timestamp
        if config_filename:
            base_name = config_filename.rsplit(".", 1)[0]
            filename = f"{base_name}_simulation.py"
        else:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"simulation_{timestamp}.py"

        return dict(content=code, filename=filename) 