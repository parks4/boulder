import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
import os
import json

# Import or define initial_config and config_to_cyto_elements as needed
from .cantera_converter import CanteraConverter, DualCanteraConverter
from .config import USE_TEMPERATURE_COLORING

# Load initial configuration
config_path = os.path.join(os.path.dirname(__file__), "data", "sample_config.json")
with open(config_path, "r") as f:
    initial_config = json.load(f)

def config_to_cyto_elements(config):
    nodes = []
    edges = []
    for comp in config["components"]:
        node_data = {
            "id": comp["id"],
            "label": f"{comp['id']} ({comp['type']})",
            "type": comp["type"],
            "properties": comp["properties"],
        }
        temp = comp["properties"].get("temperature")
        if temp is not None:
            try:
                node_data["temperature"] = float(temp)
            except Exception:
                node_data["temperature"] = temp
        nodes.append({"data": node_data})
    for conn in config["connections"]:
        edges.append({
            "data": {
                "id": conn["id"],
                "source": conn["source"],
                "target": conn["target"],
                "label": f"{conn['id']} ({conn['type']})",
                "type": conn["type"],
                "properties": conn["properties"],
            }
        })
    return nodes + edges

# Cytoscape stylesheet
cyto_stylesheet = [
    {
        "selector": "node",
        "style": {
            "content": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "background-color": (
                "mapData(temperature, 300, 2273, deepskyblue, tomato)"
                if USE_TEMPERATURE_COLORING else "#BEE"
            ),
            "text-outline-color": "#555",
            "text-outline-width": 2,
            "color": "#fff",
            "width": "80px",
            "height": "80px",
            "text-wrap": "wrap",
            "text-max-width": "80px",
        },
    },
    {
        "selector": "[type = 'Reservoir']",
        "style": {
            "shape": "octagon",
        },
    },
    {
        "selector": "edge",
        "style": {
            "content": "data(label)",
            "text-rotation": "none",
            "text-margin-y": -10,
            "curve-style": "taxi",
            "taxi-direction": "rightward",
            "taxi-turn": 50,
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#555",
            "line-color": "#555",
            "text-wrap": "wrap",
            "text-max-width": "80px",
        },
    },
]

# Define the layout
layout = html.Div(
    [
        # Hidden dummy elements for callback IDs (always present)
        html.Div(
            [
                html.Button("✕", id="delete-config-file", style={"display": "none"}),
                html.Span("", id="config-file-name-span", style={"display": "none"}),
                dcc.Upload(id="upload-config", style={"display": "none"}),
                dcc.Textarea(id="config-json-edit-textarea", style={"display": "none"}),
                dbc.Button(
                    "Save", id="save-config-json-edit-btn", style={"display": "none"}
                ),
                dbc.Button(
                    "Cancel",
                    id="cancel-config-json-edit-btn",
                    style={"display": "none"},
                ),
                html.Div(id="init-dummy-output", style={"display": "none"}),
                dcc.Interval(id="init-interval"),
                dcc.Download(id="download-python-code-file"),
            ],
            id="hidden-dummies",
            style={"display": "none"},
        ),
        html.H1("Cantera ReactorNet Visualizer"),
        # Toast for notifications
        dbc.Toast(
            id="notification-toast",
            is_open=False,
            style={"position": "fixed", "top": 66, "right": 10, "width": 350},
            duration=3000,  # Duration in milliseconds (3 seconds)
        ),
        # Stores for state management
        dcc.Store(id="config-file-name", data=""),
        dcc.Store(id="current-config", data=initial_config),
        dcc.Store(id="last-sim-python-code", data=""),
        dcc.Store(id="simulation-status", data="idle"),
        dcc.Store(id="properties-edit-mode", data=False),
        dcc.Store(id="config-json-edit-mode", data=False),
        dcc.Store(id="last-selected-element", data={}),
        # Modal for viewing config JSON
        dbc.Modal(
            [
                dbc.ModalHeader("Current Configuration JSON"),
                dbc.ModalBody(
                    [
                        html.Div(id="config-json-modal-body"),
                        dcc.Download(id="download-config-json"),
                    ]
                ),
                dbc.ModalFooter(
                    [
                        dbc.Button(
                            "Save as New File",
                            id="save-config-json-btn",
                            color="secondary",
                            className="mr-2",
                        ),
                        dbc.Button(
                            "Edit",
                            id="edit-config-json-btn",
                            color="primary",
                            className="mr-2",
                        ),
                        dbc.Button(
                            "Save",
                            id="save-config-json-edit-btn",
                            color="success",
                            className="mr-2",
                        ),
                        dbc.Button(
                            "Cancel",
                            id="cancel-config-json-edit-btn",
                            color="secondary",
                            className="ml-auto",
                        ),
                        dbc.Button(
                            "Close", id="close-config-json-modal", className="ml-auto"
                        ),
                    ]
                ),
            ],
            id="config-json-modal",
            is_open=False,
            size="lg",
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
                                    dbc.Label("Initial Temperature (K)", width=4),
                                    dbc.Col(
                                        dbc.Input(
                                            id="reactor-temp", type="number", value=300
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
                                    dbc.Label("Composition", width=4),
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
                                        dbc.Button(
                                            "Run Simulation",
                                            id="run-simulation",
                                            color="success",
                                            className="mb-2 w-100",
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
                                dbc.CardHeader("Properties"),
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
                                    cyto.Cytoscape(
                                        id="reactor-graph",
                                        # Not all Cytoscape layouts are supported by Dash.
                                        # see : https://dash.plotly.com/cytoscape/layout
                                        layout={
                                            # "name": "breadthfirst",  # https://js.cytoscape.org/#layouts/breadthfirst
                                            # "directed": True,
                                            #
                                            # "name": "grid",
                                            #
                                            "name": "cose",
                                        },
                                        style={"width": "100%", "height": "600px"},
                                        elements=config_to_cyto_elements(
                                            initial_config
                                        ),
                                        minZoom=0.33,
                                        maxZoom=3,
                                        stylesheet=cyto_stylesheet,
                                        responsive=True,
                                        # Use only supported properties:
                                        userPanningEnabled=True,
                                        userZoomingEnabled=True,
                                        boxSelectionEnabled=True,
                                    )
                                ),
                            ],
                            className="mb-3",
                        ),
                        dbc.Card(
                            [
                                dbc.CardHeader("Simulation Results"),
                                dbc.CardBody(
                                    children=[
                                        dbc.Row(
                                            [
                                                dbc.Col(
                                                    dcc.Graph(id="temperature-plot"),
                                                    width=6,
                                                ),
                                                dbc.Col(
                                                    dcc.Graph(id="pressure-plot"),
                                                    width=6,
                                                ),
                                            ],
                                            className="mb-2",
                                        ),
                                        dbc.Row(
                                            [
                                                dbc.Col(
                                                    dcc.Graph(id="species-plot"),
                                                    width=6,
                                                ),
                                                dbc.Col(html.Div(), width=6),
                                            ]
                                        ),
                                    ]
                                ),
                            ],
                        ),
                    ],
                    width=9,
                ),
            ]
        ),
        # Hidden div for storing current configuration
        dcc.Store(id="current-config", data=initial_config),
        # Hidden div for toast trigger
        dcc.Store(id="toast-trigger", data={}),
        # Add this hidden div to your layout
        html.Div(id="hidden-edge-data", style={"display": "none"}),
        # Add a store component to hold edge data
        dcc.Store(id="edge-added-store", data=None),
        # Add a hidden div to trigger initialization (of new edge creation)
        html.Div(
            id="initialization-trigger", children="init", style={"display": "none"}
        ),
        # Add a Store to keep track of edit mode
        dcc.Store(id="config-json-edit-mode", data=False),
        # Add a Store to keep track of properties panel edit mode
        dcc.Store(id="properties-edit-mode", data=False),
        dcc.Store(id="last-selected-element", data={}),
        dcc.Store(id="use-temperature-scale", data=True),
        dcc.Store(id="last-sim-python-code", data=""),
        # Hidden store to trigger keyboard actions
        dcc.Store(id="keyboard-trigger", data=""),
        dcc.Store(id="simulation-status", data="idle"),
    ]
)
