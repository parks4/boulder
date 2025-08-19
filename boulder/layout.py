"""Layout definition for the Boulder application."""

from typing import Any, Dict, List

import dash_bootstrap_components as dbc  # type: ignore
import dash_cytoscape as cyto  # type: ignore
from dash import dcc, html

from .config import THEME
from .utils import config_to_cyto_elements, get_available_cantera_mechanisms

# Enable additional Cytoscape layouts packaged with dash-cytoscape
cyto.load_extra_layouts()  # provides 'dagre', 'klay', 'cose-bilkent', etc.


def get_layout(
    initial_config: Dict[str, Any],
    cyto_stylesheet: List[Dict[str, Any]],
    original_yaml: str = "",
    config_filename: str = "",
) -> html.Div:
    """Create the main application layout."""
    return html.Div(
        id="app-container",
        children=[
            # Hidden dummy elements for callback IDs (always present)
            html.Div(
                [
                    html.Button(
                        "✕", id="delete-config-file", style={"display": "none"}
                    ),
                    html.Span(
                        "", id="config-file-name-span", style={"display": "none"}
                    ),
                    dcc.Upload(id="upload-config", style={"display": "none"}),
                    html.Div(id="init-dummy-output", style={"display": "none"}),
                    dcc.Interval(id="init-interval"),
                    # Simulation progress interval for streaming updates
                    dcc.Interval(
                        id="simulation-progress-interval",
                        interval=500,  # Update every 500ms
                        n_intervals=0,
                        disabled=True,
                    ),
                    # Light/Dark mode store
                    dcc.Store(id="theme-store", data=THEME),
                    # Intermediate stores for chained callbacks
                    dcc.Store(id="add-reactor-trigger", data={}),
                    dcc.Store(id="add-mfc-trigger", data={}),
                ],
                id="hidden-dummies",
                style={"display": "none"},
            ),
            html.H1("Boulder - Cantera ReactorNet Visualizer"),
            # Fullscreen overlay for simulation in progress
            html.Div(
                id="simulation-overlay",
                children=[
                    html.Div(className="flowing-background"),
                    html.Div("Simulating...", className="overlay-text"),
                ],
                style={
                    "display": "none",
                    "position": "fixed",
                    "inset": 0,
                    "pointerEvents": "none",
                },
            ),
            # Toast for notifications
            dbc.Toast(
                id="notification-toast",
                is_open=False,
                header="Notification",
                icon="primary",
                style={
                    "position": "fixed",
                    "top": 66,
                    "right": 10,
                    "width": 350,
                    "zIndex": 1000,
                },
                duration=2000,  # Duration in milliseconds (2 seconds)
            ),
            # Store for config file name
            dcc.Store(id="config-file-name", data=config_filename),
            # Modal for viewing config in YAML with 🪨 STONE standard
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        "Current Configuration - YAML with 🪨 STONE Standard"
                    ),
                    dbc.ModalBody(
                        [
                            html.Div(id="config-yaml-modal-body"),
                            dcc.Download(id="download-config-yaml"),
                        ]
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                "Save as New File",
                                id="save-config-yaml-btn",
                                color="primary",
                                className="mr-2",
                            ),
                            dbc.Button(
                                "Save",
                                id="save-config-yaml-edit-btn",
                                color="success",
                                className="mr-2",
                            ),
                            dbc.Button(
                                "Close",
                                id="close-config-yaml-modal",
                                color="secondary",
                                className="ml-auto",
                            ),
                        ]
                    ),
                ],
                id="config-yaml-modal",
                is_open=False,
                size="lg",
                fade=False,
            ),
            # Add Reactor Modal
            dbc.Modal(
                [
                    dbc.ModalHeader("Add Reactor"),
                    dbc.ModalBody(
                        dbc.Form(
                            [
                                dbc.Row(
                                    [
                                        dbc.Label("Reactor ID", width=4),
                                        dbc.Col(
                                            dbc.Input(
                                                id="reactor-id",
                                                type="text",
                                                placeholder="Enter reactor ID",
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Label("Reactor Type", width=4),
                                        dbc.Col(
                                            dbc.Select(
                                                id="reactor-type",
                                                options=[
                                                    {
                                                        "label": "Ideal Gas Reactor",
                                                        "value": "IdealGasReactor",
                                                    },
                                                    {
                                                        "label": "Constant Volume Reactor",
                                                        "value": "ConstVolReactor",
                                                    },
                                                    {
                                                        "label": "Constant Pressure Reactor",
                                                        "value": "ConstPReactor",
                                                    },
                                                    {
                                                        "label": "Reservoir",
                                                        "value": "Reservoir",
                                                    },
                                                ],
                                                value="IdealGasReactor",  # Set default value
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Label("Initial Temperature (°C)", width=4),
                                        dbc.Col(
                                            dbc.Input(
                                                id="reactor-temp",
                                                type="number",
                                                value=300,
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Label("Initial Pressure (Pa)", width=4),
                                        dbc.Col(
                                            dbc.Input(
                                                id="reactor-pressure",
                                                type="number",
                                                value=101325,
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Label("Thermo Report", width=4),
                                        dbc.Col(
                                            dbc.Input(
                                                id="reactor-composition",
                                                type="text",
                                                placeholder="e.g. CH4:1,O2:2,N2:7.52",
                                                value="O2:1,N2:3.76",  # Default value
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                            ]
                        )
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                "Cancel",
                                id="close-reactor-modal",
                                color="secondary",
                                className="ml-auto",
                            ),
                            dbc.Button(
                                "Add Reactor",
                                id="add-reactor",
                                color="primary",
                                disabled=True,
                            ),
                        ]
                    ),
                ],
                id="add-reactor-modal",
                is_open=False,
                fade=False,
            ),
            # Add MFC Modal
            dbc.Modal(
                [
                    dbc.ModalHeader("Add Mass Flow Controller"),
                    dbc.ModalBody(
                        dbc.Form(
                            [
                                dbc.Row(
                                    [
                                        dbc.Label("MFC ID", width=4),
                                        dbc.Col(
                                            dbc.Input(
                                                id="mfc-id",
                                                type="text",
                                                placeholder="Enter MFC ID",
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Label("Flow Rate (kg/s)", width=4),
                                        dbc.Col(
                                            dbc.Input(
                                                id="mfc-flow-rate",
                                                type="number",
                                                value=0.001,  # Default flow rate
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Label("Source Reactor", width=4),
                                        dbc.Col(
                                            dbc.Select(
                                                id="mfc-source",
                                                options=[],  # Will be populated dynamically
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Label("Target Reactor", width=4),
                                        dbc.Col(
                                            dbc.Select(
                                                id="mfc-target",
                                                options=[],  # Will be populated dynamically
                                            ),
                                            width=8,
                                        ),
                                    ],
                                    className="mb-3",
                                ),
                            ]
                        )
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                "Cancel",
                                id="close-mfc-modal",
                                color="secondary",
                                className="ml-auto",
                            ),
                            dbc.Button(
                                "Add MFC",
                                id="add-mfc",
                                color="primary",
                                disabled=True,
                            ),
                        ]
                    ),
                ],
                id="add-mfc-modal",
                is_open=False,
                fade=False,
            ),
            # Main content
            dbc.Row(
                [
                    # Left panel
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("Edit Network"),
                                    dbc.CardBody(
                                        [
                                            # Conditional display: upload or file name + X
                                            html.Div(id="config-upload-area"),
                                            dbc.Button(
                                                "Add Reactor",
                                                id="open-reactor-modal",
                                                color="primary",
                                                className="mb-2 w-100",
                                            ),
                                            dbc.Button(
                                                "Add MFC",
                                                id="open-mfc-modal",
                                                color="primary",
                                                className="mb-2 w-100",
                                            ),
                                        ]
                                    ),
                                ],
                                className="mb-3",
                            ),
                            dbc.Card(
                                [
                                    dbc.CardHeader("Simulate"),
                                    dbc.CardBody(
                                        [
                                            dbc.Row(
                                                [
                                                    dbc.Label("Mechanism", width=4),
                                                    dbc.Col(
                                                        dbc.Select(
                                                            id="mechanism-select",
                                                            options=get_available_cantera_mechanisms()
                                                            + [
                                                                {
                                                                    "label": "Custom (name)",
                                                                    "value": "custom-name",
                                                                },
                                                                {
                                                                    "label": "Custom (path)",
                                                                    "value": "custom-path",
                                                                },
                                                            ],
                                                            value="gri30.yaml",  # Default value
                                                        ),
                                                        width=8,
                                                    ),
                                                ],
                                                className="mb-3",
                                            ),
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        dbc.Input(
                                                            id="custom-mechanism-input",
                                                            type="text",
                                                            placeholder="Enter custom mechanism file name",
                                                            style={"display": "none"},
                                                        ),
                                                        width=12,
                                                    ),
                                                ],
                                                className="mb-3",
                                                id="custom-mechanism-name-row",
                                            ),
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        [
                                                            dcc.Upload(
                                                                id="custom-mechanism-upload",
                                                                children=dbc.Button(
                                                                    "Select Mechanism File",
                                                                    color="secondary",
                                                                    outline=True,
                                                                    className="w-100",
                                                                ),
                                                                style={
                                                                    "display": "none"
                                                                },
                                                                accept=".yaml,.yml",
                                                            ),
                                                            html.Div(
                                                                id="selected-mechanism-display",
                                                                style={
                                                                    "display": "none",
                                                                    "marginTop": "10px",
                                                                },
                                                                className="text-muted small",
                                                            ),
                                                        ],
                                                        width=12,
                                                    ),
                                                ],
                                                className="mb-3",
                                                id="custom-mechanism-path-row",
                                            ),
                                            dbc.Button(
                                                "Run Simulation (⌃+⏎)",
                                                id="run-simulation",
                                                color="success",
                                                className="mb-2 w-100",
                                                # Triggered by Ctrl + Enter see clientside_callback
                                            ),
                                            html.Div(
                                                id="download-python-code-btn-container",
                                                children=[],
                                            ),
                                        ]
                                    ),
                                ],
                                className="mb-3",
                            ),
                            dbc.Card(
                                [
                                    dbc.CardHeader("Input Properties"),
                                    dbc.CardBody(id="properties-panel"),
                                ],
                                className="mb-3",
                            ),
                        ],
                        width=3,
                    ),
                    # Right panel
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("Reactor Network"),
                                    dbc.CardBody(
                                        # Resizable graph container
                                        html.Div(
                                            cyto.Cytoscape(
                                                id="reactor-graph",
                                                # Not all Cytoscape layouts are supported by Dash.
                                                # see : https://dash.plotly.com/cytoscape/layout
                                                layout={
                                                    # Use dagre for a predominantly horizontal, left-to-right
                                                    # layout
                                                    # Requires dagre + cytoscape-dagre scripts, added in app
                                                    # initialization
                                                    "name": "dagre",
                                                    "rankDir": "LR",  # Left-to-right
                                                    "rankSep": 120,  # Horizontal spacing between ranks
                                                    "nodeSep": 60,  # Minimum spacing between same-rank nodes
                                                    "edgeSep": 30,  # Separation between edges
                                                    "fit": True,
                                                    "padding": 20,
                                                },
                                                style={
                                                    "width": "100%",
                                                    "height": "360px",
                                                    "minHeight": "200px",
                                                },
                                                elements=config_to_cyto_elements(
                                                    initial_config
                                                ),
                                                minZoom=0.5,
                                                maxZoom=2,
                                                stylesheet=cyto_stylesheet,
                                                responsive=True,
                                                # Use only supported properties:
                                                userPanningEnabled=True,
                                                userZoomingEnabled=True,
                                                boxSelectionEnabled=True,
                                            ),
                                            id="graph-container",
                                            style={
                                                "position": "relative",
                                                "border": "1px solid #ddd",
                                                "borderRadius": "4px",
                                                "overflow": "hidden",
                                            },
                                        ),
                                    ),
                                ],
                                className="mb-3",
                            ),
                            dbc.Card(
                                [
                                    dbc.CardHeader("Simulation Results"),
                                    dbc.CardBody(
                                        children=[
                                            dbc.Tabs(
                                                [
                                                    dbc.Tab(
                                                        label="Plots",
                                                        tab_id="plots-tab",
                                                        children=[
                                                            dbc.Row(
                                                                [
                                                                    dbc.Col(
                                                                        dcc.Graph(
                                                                            id="temperature-plot"
                                                                        ),
                                                                        width=6,
                                                                    ),
                                                                    dbc.Col(
                                                                        dcc.Graph(
                                                                            id="pressure-plot"
                                                                        ),
                                                                        width=6,
                                                                    ),
                                                                ],
                                                                className="mb-2 mt-3",
                                                            ),
                                                            dbc.Row(
                                                                [
                                                                    dbc.Col(
                                                                        dcc.Graph(
                                                                            id="species-plot"
                                                                        ),
                                                                        width=6,
                                                                    ),
                                                                    dbc.Col(
                                                                        html.Div(),
                                                                        width=6,
                                                                    ),
                                                                ]
                                                            ),
                                                        ],
                                                    ),
                                                    dbc.Tab(
                                                        label="⚠️ Error",
                                                        tab_id="error-tab",
                                                        id="error-tab-pane",
                                                        tab_style={"display": "none"},
                                                        children=[
                                                            html.Div(
                                                                [
                                                                    html.Div(
                                                                        [
                                                                            html.B(
                                                                                "⚠️ Error"
                                                                            ),
                                                                        ],
                                                                        className="mb-2",
                                                                    ),
                                                                    html.Pre(
                                                                        id="simulation-error-pane",
                                                                        className="text-danger",
                                                                        style={
                                                                            "whiteSpace": "pre-wrap",
                                                                            "fontFamily": "monospace",
                                                                            "fontSize": "0.9rem",
                                                                        },
                                                                    ),
                                                                ],
                                                                className="mt-3",
                                                            )
                                                        ],
                                                    ),
                                                    dbc.Tab(
                                                        label="Sankey Diagram",
                                                        tab_id="sankey-tab",
                                                        children=[
                                                            html.Div(
                                                                [
                                                                    dcc.Graph(
                                                                        id="sankey-plot",
                                                                        style={
                                                                            "height": "600px"
                                                                        },
                                                                    ),
                                                                ],
                                                                className="mt-3",
                                                            )
                                                        ],
                                                    ),
                                                    dbc.Tab(
                                                        label="Thermo Report",
                                                        tab_id="thermo-report-tab",
                                                        children=[
                                                            html.Div(
                                                                [
                                                                    dbc.Row(
                                                                        [
                                                                            dbc.Col(
                                                                                [
                                                                                    html.H5(
                                                                                        "Thermodynamic Report"
                                                                                    ),
                                                                                    html.Pre(
                                                                                        id="thermo-report",
                                                                                        className="thermo",
                                                                                    ),
                                                                                ],
                                                                                width=12,
                                                                            ),
                                                                        ]
                                                                    ),
                                                                ],
                                                                className="mt-3",
                                                            )
                                                        ],
                                                    ),
                                                ],
                                                id="results-tabs",
                                                active_tab="plots-tab",
                                            ),
                                        ]
                                    ),
                                ],
                                id="simulation-results-card",
                                style={"display": "none"},
                            ),
                        ],
                        width=9,
                    ),
                ]
            ),
            # Hidden div for storing current configuration
            dcc.Store(id="current-config", data=initial_config),
            # Track simulation running state
            dcc.Store(id="simulation-running", data=False),
            # Control overlay visibility with a minimum display time (set client-side)
            dcc.Store(id="overlay-visible", data=False),
            # Hidden div for toast trigger
            dcc.Store(id="toast-trigger", data={}),
            # Add a Store to keep track of edit mode
            dcc.Store(id="config-yaml-edit-mode", data=False),
            # Add a Store to keep track of properties panel edit mode
            dcc.Store(id="properties-edit-mode", data=False),
            dcc.Store(id="last-selected-element", data={}),
            dcc.Store(id="use-temperature-scale", data=True),
            dcc.Store(id="last-sim-python-code", data=""),
            # Session-specific simulation data (replaces global converters)
            dcc.Store(id="simulation-data", data=None),
            # Hidden store to trigger keyboard actions
            dcc.Store(id="keyboard-trigger", data=""),
            # Store for original YAML with comments
            dcc.Store(id="original-yaml-with-comments", data=original_yaml),
        ],
    )
