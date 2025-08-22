"""Callbacks for simulation execution and results handling."""

import base64
import os
import tempfile
from typing import Any, Dict, List, Tuple, Union

import dash
import plotly.graph_objects as go  # type: ignore
from dash import Input, Output, State, dcc

from ..simulation_worker import get_simulation_worker
from ..verbose_utils import get_verbose_logger, is_verbose_mode

logger = get_verbose_logger(__name__)

REPORT_FRACTION_TRESHOLD = 1e-7  # 0.1 ppm cutoff for thermo report


def register_callbacks(app) -> None:  # type: ignore
    """Register simulation-related callbacks."""
    # Note: simulation-running is set to True immediately via a client-side callback

    # Note: Debug logging moved to start_streaming_simulation callback

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

    # Callback to start streaming simulation
    @app.callback(
        [
            Output("simulation-progress-interval", "disabled", allow_duplicate=True),
            Output("error-tab-pane", "tab_style", allow_duplicate=True),
            Output("simulation-error-pane", "children", allow_duplicate=True),
        ],
        [
            Input("run-simulation", "n_clicks"),
        ],
        [
            State("current-config", "data"),
            State("config-file-name", "data"),
            State("mechanism-select", "value"),
            State("custom-mechanism-input", "value"),
            State("custom-mechanism-upload", "filename"),
        ],
        prevent_initial_call=True,
    )
    def start_streaming_simulation(
        n_clicks: int,
        config: Dict[str, Any],
        config_filename: str,
        mechanism_select: str,
        custom_mechanism: str,
        uploaded_filename: str,
    ) -> Tuple[bool, Dict[str, str], str]:
        """Start a background simulation with streaming updates."""
        from ..cantera_converter import (
            DualCanteraConverter,
            get_plugins,
        )

        # Always log callback invocation for debugging
        logger.info("🚀 start_streaming_simulation callback triggered!")
        logger.info(f"  n_clicks: {n_clicks}")
        logger.info(
            f"  config: {config is not None} (has {len(config.get('nodes', [])) if config else 0} nodes)"
        )
        logger.info(f"  config_filename: {config_filename}")
        logger.info(f"  mechanism_select: {mechanism_select}")

        if is_verbose_mode():
            logger.info(
                f"Starting streaming simulation with config: {config_filename or 'default'}"
            )
            logger.info(
                f"Mechanism: {mechanism_select}, Custom mechanism: {bool(custom_mechanism)}"
            )

        if not n_clicks or not config:
            logger.warning(
                f"❌ Simulation not started: n_clicks={n_clicks}, config={config is not None}"
            )
            return (True, {"display": "none"}, "")

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
            # Create unified converter
            converter = DualCanteraConverter(mechanism=mechanism, plugins=get_plugins())

            # Read simulation parameters from settings (STONE schema)
            settings: Dict[str, Any] = {}
            try:
                if isinstance(config, dict):
                    settings = config.get("settings") or {}
            except Exception:
                settings = {}

            # dt (seconds) and end_time (seconds) with sensible fallbacks
            try:
                time_step = float(settings.get("dt", 1.0))
            except Exception:
                time_step = 1.0
            try:
                simulation_time = float(
                    settings.get("end_time", settings.get("max_time", 10.0))
                )
            except Exception:
                simulation_time = 10.0

            # Clamp to safe ranges
            if time_step <= 0:
                time_step = 1.0
            if simulation_time <= 0:
                simulation_time = 10.0

            # Start background simulation
            worker = get_simulation_worker()
            worker.start_simulation(
                converter=converter,
                config=config,
                simulation_time=simulation_time,
                time_step=time_step,
            )

            logger.info("✅ Background simulation started successfully")
            logger.info("📡 Enabling interval updates (500ms)")
            return (False, {"display": "none"}, "")

        except Exception as e:
            logger.error(f"❌ Failed to start simulation: {e}", exc_info=True)
            return (True, {"display": "none"}, "")

    # Streaming update callback - updates plots as simulation progresses
    @app.callback(
        [
            Output("temperature-plot", "figure"),
            Output("pressure-plot", "figure"),
            Output("species-plot", "figure"),
            Output("last-sim-python-code", "data"),
            Output("simulation-results-card", "style"),
            Output("simulation-data", "data"),
            Output("simulation-error-display", "children"),
            Output("simulation-error-display", "style"),
            Output("simulation-error-pane", "children"),
            Output("error-tab-pane", "tab_style"),
            Output("simulation-progress-interval", "disabled"),
            Output("simulation-running", "data"),
        ],
        [
            Input("simulation-progress-interval", "n_intervals"),
            Input("theme-store", "data"),
            Input("simulation-running", "data"),
        ],
        [
            State("last-selected-element", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_streaming_simulation(
        n_intervals: int,
        theme: str,
        simulation_running: bool,
        last_selected: Dict[str, Any],
    ) -> Tuple[
        Any,
        Any,
        Any,
        Any,
        Dict[str, str],
        Dict[str, Any],
        Any,
        Dict[str, str],
        Any,
        Dict[str, str],
        bool,
        bool,
    ]:
        """Update plots with streaming simulation data."""
        from ..utils import apply_theme_to_figure

        # Log every streaming update for debugging
        logger.info(f"📊 update_streaming_simulation called (interval #{n_intervals})")
        logger.info(f"  simulation_running from client: {simulation_running}")

        worker = get_simulation_worker()
        progress = worker.get_progress()

        logger.info(
            f"  Progress: running={progress.is_running}, complete={progress.is_complete}"
        )
        logger.info(
            f"  Data: {len(progress.times)} time points, {len(progress.reactors_series)} reactors"
        )

        # If simulation not running and not complete, show error if present and disable interval
        if not progress.is_running and not progress.is_complete:
            error_tab_style = {"display": "none"}
            results_card_style = {"display": "none"}
            if progress.error_message:
                error_tab_style = {"display": "block"}
                # Ensure the results pane is visible so the error is noticeable
                results_card_style = {"display": "block"}

            # One-line banner content/style (CSS handles ellipsis)
            banner_text: Any
            if progress.error_message:
                # Build a concise one-liner from the first meaningful lines
                stripped_lines = [
                    line.strip()
                    for line in progress.error_message.splitlines()
                    if line.strip()
                ]
                # Drop decorative lines like ******
                core_lines = [line for line in stripped_lines if set(line) != {"*"}]
                summary = ""
                for line in core_lines[:4]:  # consider first few lines
                    candidate = (summary + " — " + line) if summary else line
                    if len(candidate) > 200:
                        summary = candidate[:200]
                        break
                    summary = candidate
                if not summary and stripped_lines:
                    summary = stripped_lines[0]
                banner_text = f"⚠️ {summary}"
                banner_style = {
                    "display": "block",
                    "color": "#dc3545",
                    "whiteSpace": "nowrap",
                    "overflow": "hidden",
                    "textOverflow": "ellipsis",
                }
            else:
                banner_text = dash.no_update
                banner_style = {"display": "none"}

            return (
                go.Figure(),
                go.Figure(),
                go.Figure(),
                "",
                results_card_style,
                {},
                banner_text,
                banner_style,
                (progress.error_message or ""),
                error_tab_style,
                True,  # Disable interval
                False,  # Not running
            )

        # Build plots from current progress
        temp_fig = go.Figure()
        press_fig = go.Figure()
        species_fig = go.Figure()

        if progress.reactors_series and progress.times:
            # Determine which reactor to show based on selection
            selected_node_id = None
            if last_selected and last_selected.get("type") == "node":
                sel_data = last_selected.get("data") or {}
                node_kind = (sel_data.get("type") or "").lower()
                if node_kind in {"reservoir", "massflowcontroller", "valve", "wall"}:
                    # Do not show plots for non-reactors
                    return (
                        go.Figure(),
                        go.Figure(),
                        go.Figure(),
                        dash.no_update,
                        {"display": "none"},
                        {},
                        dash.no_update,
                        {"display": "none"},
                        dash.no_update,
                        {"display": "none"},
                        True,
                        False,
                    )
                selected_node_id = sel_data.get("id")

            # Use selected node if available and exists in data, otherwise use first reactor
            if selected_node_id and selected_node_id in progress.reactors_series:
                reactor_id = selected_node_id
            else:
                reactor_id = next(iter(progress.reactors_series.keys()))

            series = progress.reactors_series[reactor_id]

            # Convert temperature from K to °C for display
            temp_c = [float(t) - 273.15 for t in (series.get("T") or [])]
            temp_fig.add_trace(
                go.Scatter(x=progress.times, y=temp_c, name=f"{reactor_id} T")
            )
            temp_fig.update_layout(
                title=f"Temperature vs Time — {reactor_id}",
                xaxis=dict(title=dict(text="Time (s)", font=dict(size=16))),
                yaxis=dict(title=dict(text="Temperature (°C)", font=dict(size=16))),
                margin=dict(t=0, b=40, l=60, r=20),
            )
            temp_fig = apply_theme_to_figure(temp_fig, theme)

            press_fig.add_trace(
                go.Scatter(x=progress.times, y=series["P"], name=f"{reactor_id} P")
            )
            press_fig.update_layout(
                title=f"Pressure vs Time — {reactor_id}",
                xaxis=dict(title=dict(text="Time (s)", font=dict(size=16))),
                yaxis=dict(title=dict(text="Pressure (Pa)", font=dict(size=16))),
                margin=dict(t=0, b=40, l=60, r=20),
            )
            press_fig = apply_theme_to_figure(press_fig, theme)

            for species_name, concentrations in series["X"].items():
                if max(concentrations or [0]) > 0.01:
                    species_fig.add_trace(
                        go.Scatter(
                            x=progress.times, y=concentrations, name=species_name
                        )
                    )
            species_fig.update_layout(
                title=f"Species Concentrations vs Time — {reactor_id}",
                xaxis=dict(title=dict(text="Time (s)", font=dict(size=16))),
                yaxis=dict(title=dict(text="Mole Fraction", font=dict(size=16))),
                margin=dict(t=0, b=40, l=60, r=20),
            )
            species_fig = apply_theme_to_figure(species_fig, theme)

        # Prepare simulation data
        results = {
            "time": progress.times,
            "reactors": progress.reactors_series,
        }
        # Attach Sankey data if available from the background worker
        if progress.sankey_links and progress.sankey_nodes:
            results["sankey_links"] = progress.sankey_links
            results["sankey_nodes"] = progress.sankey_nodes

        simulation_data = {
            "results": results,
            "code": progress.code_str,
            "mechanism": progress.mechanism,
            "reactor_reports": progress.reactor_reports,
        }

        # Store live objects in global singleton to avoid serialization issues
        from ..live_simulation import clear_live_simulation, update_live_simulation

        if progress.is_complete and not progress.is_running and progress.network:
            try:
                # Store live objects in singleton
                update_live_simulation(
                    network=progress.network,
                    reactors=progress.reactors_dict,
                    mechanism=progress.mechanism,
                )
                logger.info(
                    "✅ Stored live simulation objects in singleton for spatial analysis"
                )
            except Exception as e:
                logger.warning(f"⚠️ Could not store live simulation objects: {e}")
                clear_live_simulation()
        elif not progress.is_running and not progress.is_complete:
            # Clear on simulation reset/failure
            clear_live_simulation()

        # Handle non-fatal warnings (runtime notices)
        error_message = progress.error_message or ""
        error_tab_style = {"display": "block"} if error_message else {"display": "none"}
        if error_message:
            stripped_lines = [
                line.strip() for line in error_message.splitlines() if line.strip()
            ]
            core_lines = [line for line in stripped_lines if set(line) != {"*"}]
            summary = ""
            for line in core_lines[:4]:
                candidate = (summary + " — " + line) if summary else line
                if len(candidate) > 200:
                    summary = candidate[:200]
                    break
                summary = candidate
            if not summary and stripped_lines:
                summary = stripped_lines[0]
            banner_text = f"⚠️ {summary}"
            banner_style = {
                "display": "block",
                "color": "#dc3545",
                "whiteSpace": "nowrap",
                "overflow": "hidden",
                "textOverflow": "ellipsis",
            }
        else:
            banner_text = dash.no_update
            banner_style = {"display": "none"}

        # Check if simulation is complete - disable interval when done
        interval_disabled = progress.is_complete or not progress.is_running
        simulation_running = progress.is_running

        return (
            temp_fig.to_dict(),
            press_fig.to_dict(),
            species_fig.to_dict(),
            progress.code_str,
            {"display": "block"},
            simulation_data,
            banner_text,
            banner_style,
            (progress.error_message or ""),
            error_tab_style,
            interval_disabled,
            simulation_running,
        )

    print("✅ [SIMULATION CALLBACKS] Streaming update callback registered successfully")

    # Overlay style now handled client-side for zero-lag responsiveness

    # Conditionally render Download .py button
    @app.callback(
        Output("download-python-code-btn-container", "children"),
        Input("last-sim-python-code", "data"),
        prevent_initial_call=False,
    )
    def show_download_button(code_str: str) -> List[Any]:
        import dash_bootstrap_components as dbc  # type: ignore

        # Always show download button with unified converter
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

    # Enable/disable Download .py button based on code availability
    @app.callback(
        [
            Output("download-python-code-btn", "disabled"),
            Output("download-python-code-btn", "color"),
        ],
        [Input("last-sim-python-code", "data")],
        prevent_initial_call=False,
    )
    def toggle_download_button(code_str: str) -> Tuple[bool, str]:
        # Always enable if we have code (unified converter always generates code)
        if code_str and code_str.strip():
            return False, "primary"  # enabled, darker
        return True, "secondary"  # disabled, light/grey

    # Clear last-sim-python-code on parameter or config change
    @app.callback(
        Output("last-sim-python-code", "data", allow_duplicate=True),
        [
            Input("save-config-yaml-edit-btn", "n_clicks"),
            Input("upload-config", "contents"),
            Input("add-reactor-trigger", "data"),
            Input("add-mfc-trigger", "data"),
            Input("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def clear_python_code_on_edit(*_: Any) -> str:
        return ""

    # Hide simulation results (plots & Sankey diagrams) on configuration change
    @app.callback(
        [
            Output("simulation-results-card", "style", allow_duplicate=True),
            Output("simulation-data", "data", allow_duplicate=True),
        ],
        [
            Input("save-config-yaml-edit-btn", "n_clicks"),
            Input("upload-config", "contents"),
            Input("add-reactor-trigger", "data"),
            Input("add-mfc-trigger", "data"),
            Input("current-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def hide_results_on_config_change(*_: Any) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """Hide plots and Sankey diagrams when configuration changes."""
        # Also clear singleton when config changes
        from ..live_simulation import clear_live_simulation

        clear_live_simulation()
        return {"display": "none"}, {}

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

    # Update plots when a reactor node is selected in the graph
    @app.callback(
        [
            Output("temperature-plot", "figure", allow_duplicate=True),
            Output("pressure-plot", "figure", allow_duplicate=True),
            Output("species-plot", "figure", allow_duplicate=True),
        ],
        [
            Input("last-selected-element", "data"),
            Input("simulation-data", "data"),
            Input("theme-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_plots_for_selected_node(
        last_selected: Dict[str, Any], simulation_data: Dict[str, Any], theme: str
    ) -> Tuple[Any, Any, Any]:
        import plotly.graph_objects as go

        from ..utils import apply_theme_to_figure

        if not last_selected or last_selected.get("type") != "node":
            # Clear plots when nothing appropriate is selected
            empty = go.Figure().to_dict()
            return empty, empty, empty

        node_id = (last_selected.get("data") or {}).get("id")
        node_type = (last_selected.get("data") or {}).get("type") or ""
        # Only show plots for actual reactors; clear otherwise
        if isinstance(node_type, str) and node_type.lower() in {
            "reservoir",
            "massflowcontroller",
            "valve",
            "wall",
        }:
            empty = go.Figure().to_dict()
            return empty, empty, empty
        if not node_id or not simulation_data or "results" not in simulation_data:
            # Ignore selections that do not correspond to simulated reactors
            return dash.no_update, dash.no_update, dash.no_update

        results = simulation_data["results"]
        reactors = results.get("reactors") or {}

        if node_id not in reactors:
            return dash.no_update, dash.no_update, dash.no_update

        times = results.get("time", [])
        node_series = reactors[node_id]

        # Temperature plot
        temp_fig = go.Figure()
        # Convert temperature from K to °C for display
        temp_c_sel = [float(t) - 273.15 for t in (node_series.get("T") or [])]
        temp_fig.add_trace(go.Scatter(x=times, y=temp_c_sel, name=f"{node_id} T"))
        temp_fig.update_layout(
            title=f"Temperature vs Time — {node_id}",
            xaxis=dict(title=dict(text="Time (s)", font=dict(size=16))),
            yaxis=dict(title=dict(text="Temperature (°C)", font=dict(size=16))),
            margin=dict(t=0, b=40, l=60, r=20),
        )
        temp_fig = apply_theme_to_figure(temp_fig, theme)

        # Pressure plot
        press_fig = go.Figure()
        press_fig.add_trace(
            go.Scatter(x=times, y=node_series["P"], name=f"{node_id} P")
        )
        press_fig.update_layout(
            title=f"Pressure vs Time — {node_id}",
            xaxis=dict(title=dict(text="Time (s)", font=dict(size=16))),
            yaxis=dict(title=dict(text="Pressure (Pa)", font=dict(size=16))),
            margin=dict(t=0, b=40, l=60, r=20),
        )
        press_fig = apply_theme_to_figure(press_fig, theme)

        # Species plot
        species_fig = go.Figure()
        for species_name, concentrations in node_series["X"].items():
            if max(concentrations or [0]) > 0.01:
                species_fig.add_trace(
                    go.Scatter(x=times, y=concentrations, name=species_name)
                )
        species_fig.update_layout(
            title=f"Species Concentrations vs Time — {node_id}",
            xaxis=dict(title=dict(text="Time (s)", font=dict(size=16))),
            yaxis=dict(title=dict(text="Mole Fraction", font=dict(size=16))),
            margin=dict(t=0, b=40, l=60, r=20),
        )
        species_fig = apply_theme_to_figure(species_fig, theme)

        return temp_fig.to_dict(), press_fig.to_dict(), species_fig.to_dict()

    # Update composition plot and thermo report when a reactor node is selected
    @app.callback(
        [
            Output("thermo-report", "children"),
        ],
        [
            Input("last-selected-element", "data"),
            Input("simulation-data", "data"),
            Input("theme-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_composition_for_selected_node(
        last_selected: Dict[str, Any], simulation_data: Dict[str, Any], theme: str
    ) -> Tuple[str]:
        # Only act if we have simulation results and a node selection
        if not simulation_data or "results" not in simulation_data:
            return ("No simulation data available.",)

        if not last_selected or last_selected.get("type") != "node":
            return ("Select a reactor node to view thermodynamic data.",)

        node_id = (last_selected.get("data") or {}).get("id")
        if not node_id:
            return ("No node selected.",)

        # Use the pre-generated reactor reports from simulation data
        reactor_reports = simulation_data.get("reactor_reports", {})
        if node_id not in reactor_reports:
            return (
                f"Thermo report unavailable for {node_id}. Please re-run the simulation.",
            )

        reports = reactor_reports[node_id]
        reactor_report = reports.get("reactor_report", "")
        thermo_report = reports.get("thermo_report", "")

        combined = (
            f"THERMODYNAMIC REPORT — {node_id}\n"
            f"{'=' * 70}\n\n"
            f"[Reactor]\n{reactor_report}\n"
            f"\n[Gas (Solution)]\n{thermo_report}"
        )

        return (combined,)
