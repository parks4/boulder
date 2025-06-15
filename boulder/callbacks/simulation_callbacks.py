"""Callbacks for simulation execution and results handling."""

import base64
import datetime
import os
import tempfile
from typing import Any, Dict, List, Tuple, Union

import dash
import plotly.graph_objects as go  # type: ignore
from dash import Input, Output, State


def register_callbacks(app) -> None:  # type: ignore
    """Register simulation-related callbacks."""

    # Callback to show/hide custom mechanism input
    @app.callback(
        [
            Output("custom-mechanism-input", "style"),
            Output("custom-mechanism-upload", "style"),
            Output("selected-mechanism-display", "style"),
        ],
        Input("mechanism-select", "value"),
        prevent_initial_call=False,
    )
    def toggle_custom_mechanism_input(
        mechanism_value: str,
    ) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
        """Show appropriate custom mechanism input based on selection."""
        if mechanism_value == "custom-name":
            return {"display": "block"}, {"display": "none"}, {"display": "none"}
        elif mechanism_value == "custom-path":
            return {"display": "none"}, {"display": "block"}, {"display": "none"}
        else:
            return {"display": "none"}, {"display": "none"}, {"display": "none"}

    # Callback to handle file upload for custom mechanism
    @app.callback(
        [
            Output("selected-mechanism-display", "children"),
            Output("selected-mechanism-display", "style", allow_duplicate=True),
        ],
        Input("custom-mechanism-upload", "contents"),
        State("custom-mechanism-upload", "filename"),
        prevent_initial_call=True,
    )
    def handle_mechanism_upload(
        contents: str, filename: str
    ) -> Tuple[str, Dict[str, str]]:
        """Handle uploaded mechanism file."""
        if contents is None:
            return "", {"display": "none"}

        try:
            # Decode the uploaded file
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)

            # Save to a temporary location
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, filename)

            with open(temp_path, "wb") as f:
                f.write(decoded)

            # Display the file info
            display_text = f"Selected: {filename} ({temp_path})"
            return display_text, {"display": "block", "marginTop": "10px"}

        except Exception as e:
            return f"Error: {str(e)}", {
                "display": "block",
                "marginTop": "10px",
                "color": "red",
            }

    # Callback to run simulation and update plots
    @app.callback(
        [
            Output("temperature-plot", "figure"),
            Output("pressure-plot", "figure"),
            Output("species-plot", "figure"),
            Output("last-sim-python-code", "data"),
            Output("simulation-error-display", "children"),
            Output("simulation-error-display", "style"),
            Output("simulation-results-card", "style"),
            Output("simulation-data", "data"),
        ],
        [
            Input("run-simulation", "n_clicks"),
            Input("theme-store", "data"),  # Add theme as input
        ],
        [
            State("current-config", "data"),
            State("config-file-name", "data"),
            State("mechanism-select", "value"),
            State("custom-mechanism-input", "value"),
            State("custom-mechanism-upload", "filename"),
            State("simulation-data", "data"),  # Keep existing simulation data
        ],
        prevent_initial_call=True,
    )
    def run_simulation(
        n_clicks: int,
        theme: str,
        config: Dict[str, Any],
        config_filename: str,
        mechanism_select: str,
        custom_mechanism: str,
        uploaded_filename: str,
        existing_sim_data: Dict[str, Any],
    ) -> Tuple[Any, Any, Any, str, Any, Dict[str, str], Dict[str, str], Dict[str, Any]]:
        from ..cantera_converter import CanteraConverter, DualCanteraConverter
        from ..config import USE_DUAL_CONVERTER
        from ..utils import apply_theme_to_figure

        # Get the trigger context
        ctx = dash.callback_context
        triggered_id = (
            ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None
        )

        # If only theme changed and we have existing simulation data, just re-theme the plots
        if (
            triggered_id == "theme-store"
            and existing_sim_data
            and existing_sim_data.get("results")
        ):
            results = existing_sim_data["results"]
            code_str = existing_sim_data.get("code", "")

            # Create temperature plot
            temp_fig = go.Figure()
            temp_fig.add_trace(
                go.Scatter(
                    x=results["time"], y=results["temperature"], name="Temperature"
                )
            )
            temp_fig.update_layout(
                title="Temperature vs Time",
                xaxis_title="Time (s)",
                yaxis_title="Temperature (K)",
            )
            temp_fig = apply_theme_to_figure(temp_fig, theme)

            # Create pressure plot
            press_fig = go.Figure()
            press_fig.add_trace(
                go.Scatter(x=results["time"], y=results["pressure"], name="Pressure")
            )
            press_fig.update_layout(
                title="Pressure vs Time",
                xaxis_title="Time (s)",
                yaxis_title="Pressure (Pa)",
            )
            press_fig = apply_theme_to_figure(press_fig, theme)

            # Create species plot
            species_fig = go.Figure()
            for species, concentrations in results["species"].items():
                if (
                    max(concentrations) > 0.01
                ):  # Only show species with significant concentration
                    species_fig.add_trace(
                        go.Scatter(x=results["time"], y=concentrations, name=species)
                    )
            species_fig.update_layout(
                title="Species Concentrations vs Time",
                xaxis_title="Time (s)",
                yaxis_title="Mole Fraction",
            )
            species_fig = apply_theme_to_figure(species_fig, theme)

            return (
                temp_fig.to_dict(),
                press_fig.to_dict(),
                species_fig.to_dict(),
                code_str,
                dash.no_update,
                {"display": "none"},
                {"display": "block"},
                existing_sim_data,  # Return existing data
            )

        # Proceed with full simulation if button clicked or no existing data
        if not config:
            return {}, {}, {}, "", "", {"display": "none"}, {"display": "none"}, {}

        # Determine the mechanism to use
        if mechanism_select == "custom-name":
            mechanism = (
                custom_mechanism
                if custom_mechanism and custom_mechanism.strip()
                else "gri30.yaml"
            )
        elif mechanism_select == "custom-path":
            if uploaded_filename:
                # Use the uploaded file path from temp directory
                temp_dir = tempfile.gettempdir()
                mechanism = os.path.join(temp_dir, uploaded_filename)
            else:
                mechanism = "gri30.yaml"  # Fallback
        else:
            mechanism = mechanism_select

        try:
            # Debug: Log the mechanism being used
            print(f"[DEBUG] Using mechanism: {mechanism}")

            if USE_DUAL_CONVERTER:
                dual_converter = DualCanteraConverter(mechanism=mechanism)
                print(
                    f"[DEBUG] DualCanteraConverter mechanism: {dual_converter.mechanism}"
                )
                print(
                    f"[DEBUG] DualCanteraConverter gas name: {dual_converter.gas.name}"
                )
                network, results, code_str = dual_converter.build_network_and_code(
                    config, theme=theme
                )
            else:
                single_converter = CanteraConverter(mechanism=mechanism)
                print(
                    f"[DEBUG] CanteraConverter mechanism: {single_converter.mechanism}"
                )
                print(f"[DEBUG] CanteraConverter gas name: {single_converter.gas.name}")
                network, results = single_converter.build_network(config, theme=theme)
                code_str = ""

            # Create temperature plot
            temp_fig = go.Figure()
            temp_fig.add_trace(
                go.Scatter(
                    x=results["time"], y=results["temperature"], name="Temperature"
                )
            )
            temp_fig.update_layout(
                title="Temperature vs Time",
                xaxis_title="Time (s)",
                yaxis_title="Temperature (K)",
            )
            temp_fig = apply_theme_to_figure(temp_fig, theme)

            # Create pressure plot
            press_fig = go.Figure()
            press_fig.add_trace(
                go.Scatter(x=results["time"], y=results["pressure"], name="Pressure")
            )
            press_fig.update_layout(
                title="Pressure vs Time",
                xaxis_title="Time (s)",
                yaxis_title="Pressure (Pa)",
            )
            press_fig = apply_theme_to_figure(press_fig, theme)

            # Create species plot
            species_fig = go.Figure()
            for species, concentrations in results["species"].items():
                if (
                    max(concentrations) > 0.01
                ):  # Only show species with significant concentration
                    species_fig.add_trace(
                        go.Scatter(x=results["time"], y=concentrations, name=species)
                    )
            species_fig.update_layout(
                title="Species Concentrations vs Time",
                xaxis_title="Time (s)",
                yaxis_title="Mole Fraction",
            )
            species_fig = apply_theme_to_figure(species_fig, theme)

            if USE_DUAL_CONVERTER and code_str:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                config_file_str = (
                    config_filename
                    if config_filename
                    else "(no file, edited or generated in app)"
                )
                header = (
                    f'"""\n'
                    f"This file was automatically generated by Boulder on {now}.\n"
                    f"Configuration source: {config_file_str}\n"
                    f"\n"
                    f"This script defines all Cantera objects (reactors, connections), "
                    f"builds the reactor network, and runs a sample simulation loop.\n"
                    f"You can modify and run this script independently with Cantera installed.\n"
                    f'"""\n'
                )
                code_str = header + code_str
            return (
                temp_fig.to_dict(),
                press_fig.to_dict(),
                species_fig.to_dict(),
                code_str,
                "",
                {"display": "none"},
                {"display": "block"},
                {
                    "mechanism": mechanism,
                    "config": config,
                    "results": results,
                    "code": code_str,
                },
            )
        except Exception as e:
            # Create user-friendly error message
            import dash_bootstrap_components as dbc
            from dash import html

            error_msg = str(e)
            mechanism_name = mechanism if isinstance(mechanism, str) else str(mechanism)

            # Provide specific error messages for common issues
            if (
                "No such file or directory" in error_msg
                or "cannot find" in error_msg.lower()
            ):
                user_message = (
                    f"Mechanism file '{mechanism_name}' could not be found. "
                    "Please check the file path or select a different mechanism."
                )
            elif "failed to load mechanism" in error_msg.lower():
                user_message = (
                    f"Failed to load mechanism '{mechanism_name}'. "
                    "The file may be corrupted or incompatible."
                )
            elif "solution" in error_msg.lower() and "error" in error_msg.lower():
                user_message = (
                    f"Error creating Cantera solution with mechanism '{mechanism_name}'. "
                    "Please verify the mechanism file format."
                )
            elif "network" in error_msg.lower():
                user_message = "Error building reactor network. Please check your reactor configuration."
            else:
                user_message = f"Simulation failed: {error_msg}"

            error_display = dbc.Alert(
                [
                    html.H6("Simulation Error", className="alert-heading"),
                    html.P(user_message),
                    html.Hr(),
                    html.P(
                        [
                            "Details: ",
                            html.Code(error_msg, style={"fontSize": "0.8em"}),
                        ],
                        className="mb-0 small text-muted",
                    ),
                ],
                color="danger",
                dismissable=True,
                is_open=True,
            )

            return (
                {},
                {},
                {},
                "",
                error_display,
                {"display": "block"},
                {"display": "none"},
                {},
            )

    # Conditionally render Download .py button
    @app.callback(
        Output("download-python-code-btn-container", "children"),
        Input("last-sim-python-code", "data"),
        prevent_initial_call=False,
    )
    def show_download_button(code_str: str) -> List[Any]:
        import dash_bootstrap_components as dbc  # type: ignore
        from dash import dcc

        from ..config import USE_DUAL_CONVERTER

        if USE_DUAL_CONVERTER:
            return [
                dbc.Button(
                    "Download .py",
                    id="download-python-code-btn",
                    color="secondary",
                    className="mb-2 w-100",
                    n_clicks=0,
                    disabled=not (code_str and code_str.strip()),
                ),
                dcc.Download(id="download-python-code"),
            ]
        return []

    # Only enable/disable Download .py button if DualCanteraConverter is used
    @app.callback(
        [
            Output("download-python-code-btn", "disabled"),
            Output("download-python-code-btn", "color"),
        ],
        [Input("last-sim-python-code", "data")],
        prevent_initial_call=False,
    )
    def toggle_download_button(code_str: str) -> Tuple[bool, str]:
        from ..config import USE_DUAL_CONVERTER

        if not USE_DUAL_CONVERTER:
            return True, "secondary"
        if code_str and code_str.strip():
            return False, "primary"  # enabled, darker
        return True, "secondary"  # disabled, light/grey

    # Clear last-sim-python-code on parameter or config change
    @app.callback(
        Output("last-sim-python-code", "data", allow_duplicate=True),
        [
            Input({"type": "prop-edit", "prop": dash.ALL}, "value"),
            Input("save-config-yaml-edit-btn", "n_clicks"),
            Input("upload-config", "contents"),
        ],
        prevent_initial_call=True,
    )
    def clear_python_code_on_edit(*_: Any) -> str:
        return ""

    # Download .py file when button is clicked
    @app.callback(
        Output("download-python-code", "data"),
        Input("download-python-code-btn", "n_clicks"),
        State("last-sim-python-code", "data"),
        prevent_initial_call=True,
    )
    def trigger_download_py(n_clicks: int, code_str: str) -> Union[Dict[str, str], Any]:
        if n_clicks and code_str and code_str.strip():
            return dict(content=code_str, filename="cantera_simulation.py")
        return dash.no_update

    # Callback for Sankey diagram
    @app.callback(
        Output("sankey-plot", "figure"),
        [
            Input("results-tabs", "active_tab"),
            Input("simulation-data", "data"),
            Input("theme-store", "data"),  # Add theme as input
        ],
        State("reactor-graph", "elements"),
        prevent_initial_call=True,
    )
    def update_sankey_plot(
        active_tab: str,
        simulation_data: Dict[str, Any],
        theme: str,
        reactor_elements: List[Dict[str, Any]],
    ) -> Union[Dict[str, Any], Any]:
        """Generate Sankey diagram when the Sankey tab is selected."""
        import dash
        import plotly.graph_objects as go

        from ..sankey import plot_sankey_diagram_from_links_and_nodes
        from ..utils import get_sankey_theme_config

        # Only generate if Sankey tab is active
        if active_tab != "sankey-tab":
            return dash.no_update

        # Check if we have simulation results
        if not simulation_data or "results" not in simulation_data:
            return dash.no_update

        results = simulation_data["results"]
        links = results.get("sankey_links")
        nodes = results.get("sankey_nodes")

        # Check if Sankey data is available
        if not links or not nodes:
            sankey_theme = get_sankey_theme_config(theme)
            fig = go.Figure()
            fig.add_annotation(
                text="Sankey diagram data not available for this simulation.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="#dc3545" if theme == "light" else "#ff6b6b"),
                align="center",
            )
            fig.update_layout(
                title="Energy Flow Sankey Diagram",
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                plot_bgcolor=sankey_theme["plot_bgcolor"],
                paper_bgcolor=sankey_theme["paper_bgcolor"],
                font=sankey_theme["font"],
                margin=dict(l=10, r=10, t=40, b=10),
                height=400,
            )
            return fig.to_dict()

        try:
            # Create the Sankey plot with theme-aware styling
            sankey_theme = get_sankey_theme_config(theme)
            fig = plot_sankey_diagram_from_links_and_nodes(
                links, nodes, show=False, theme=theme
            )

            # Update layout with theme styling
            fig.update_layout(
                title="Energy Flow Sankey Diagram",
                font=sankey_theme["font"],
                paper_bgcolor=sankey_theme["paper_bgcolor"],
                plot_bgcolor=sankey_theme["plot_bgcolor"],
                margin=dict(l=10, r=10, t=40, b=10),
            )

            return fig.to_dict()

        except Exception as e:
            # Return empty figure with error message if something goes wrong
            sankey_theme = get_sankey_theme_config(theme)
            fig = go.Figure()
            fig.add_annotation(
                text=f"Error generating Sankey diagram:<br>{str(e)}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="#dc3545" if theme == "light" else "#ff6b6b"),
                align="center",
            )
            fig.update_layout(
                title="Energy Flow Sankey Diagram",
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                plot_bgcolor=sankey_theme["plot_bgcolor"],
                paper_bgcolor=sankey_theme["paper_bgcolor"],
                font=sankey_theme["font"],
                margin=dict(l=10, r=10, t=40, b=10),
                height=400,
            )
            return fig.to_dict()
