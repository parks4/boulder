import dash
from dash import html, dcc, Input, Output, State
import dash_cytoscape as cyto
import json
import plotly.graph_objects as go
import os
from .cantera_converter import CanteraConverter
import dash_bootstrap_components as dbc
import base64

# Initialize the Dash app with Bootstrap
app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.7.2/font/bootstrap-icons.css",
    ],
    external_scripts=[
        "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdn.jsdelivr.net/npm/cytoscape-edgehandles@4.0.1/cytoscape-edgehandles.min.js",
    ],
)
server = app.server  # Expose the server for deployment

# Initialize the Cantera converter
converter = CanteraConverter()

# Load initial configuration
config_path = os.path.join(os.path.dirname(__file__), "data", "sample_config.json")
with open(config_path, "r") as f:
    initial_config = json.load(f)


# Convert components to Cytoscape elements
def config_to_cyto_elements(config):
    nodes = []
    edges = []

    # Add nodes
    for comp in config["components"]:
        nodes.append(
            {
                "data": {
                    "id": comp["id"],
                    "label": f"{comp['id']} ({comp['type']})",
                    "type": comp["type"],
                    "properties": comp["properties"],
                }
            }
        )

    # Add edges
    for conn in config["connections"]:
        edges.append(
            {
                "data": {
                    "id": conn["id"],
                    "source": conn["source"],
                    "target": conn["target"],
                    "label": f"{conn['id']} ({conn['type']})",
                    "type": conn["type"],
                    "properties": conn["properties"],
                }
            }
        )

    return nodes + edges


# Define the layout
app.layout = html.Div(
    [
        html.H1("Cantera ReactorNet Visualizer"),
        # Toast for notifications
        dbc.Toast(
            id="notification-toast",
            is_open=False,
            style={"position": "fixed", "top": 66, "right": 10, "width": 350},
            duration=1500,  # Duration in milliseconds (0.5 seconds)
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
                                        dcc.Upload(
                                            id="upload-config",
                                            children=html.Div(
                                                [
                                                    "Drop or ",
                                                    html.A("Select a Config File"),
                                                ]
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
                                        layout={"name": "cose"},
                                        style={"width": "100%", "height": "600px"},
                                        elements=config_to_cyto_elements(
                                            initial_config
                                        ),
                                        stylesheet=[
                                            {
                                                "selector": "node",
                                                "style": {
                                                    "content": "data(label)",
                                                    "text-valign": "center",
                                                    "text-halign": "center",
                                                    "background-color": "#BEE",
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
                                        ],
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
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                dcc.Graph(id="temperature-plot"),
                                                width=4,
                                            ),
                                            dbc.Col(
                                                dcc.Graph(id="pressure-plot"), width=4
                                            ),
                                            dbc.Col(
                                                dcc.Graph(id="species-plot"), width=4
                                            ),
                                        ]
                                    )
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
    ]
)


# Callback to open/close Reactor modal
@app.callback(
    Output("add-reactor-modal", "is_open"),
    [
        Input("open-reactor-modal", "n_clicks"),
        Input("close-reactor-modal", "n_clicks"),
        Input("add-reactor", "n_clicks"),
    ],
    [State("add-reactor-modal", "is_open")],
)
def toggle_reactor_modal(n1, n2, n3, is_open):
    if n1 or n2 or n3:
        return not is_open
    return is_open


# Callback to open/close MFC modal
@app.callback(
    Output("add-mfc-modal", "is_open"),
    [
        Input("open-mfc-modal", "n_clicks"),
        Input("close-mfc-modal", "n_clicks"),
        Input("add-mfc", "n_clicks"),
    ],
    [State("add-mfc-modal", "is_open")],
)
def toggle_mfc_modal(n1, n2, n3, is_open):
    if n1 or n2 or n3:
        return not is_open
    return is_open


# Callback to update MFC source/target options
@app.callback(
    [Output("mfc-source", "options"), Output("mfc-target", "options")],
    [Input("current-config", "data")],
)
def update_mfc_options(config):
    # Allow both Reservoirs and Reactors as sources/targets
    valid_types = ["IdealGasReactor", "ConstVolReactor", "ConstPReactor", "Reservoir"]
    options = [
        {"label": comp["id"], "value": comp["id"]}
        for comp in config["components"]
        if comp["type"] in valid_types
    ]
    return options, options


# Callback to add new reactor
@app.callback(
    [
        Output("current-config", "data", allow_duplicate=True),
        Output("notification-toast", "is_open", allow_duplicate=True),
        Output("notification-toast", "children", allow_duplicate=True),
    ],
    [Input("add-reactor", "n_clicks")],
    [
        State("reactor-id", "value"),
        State("reactor-type", "value"),
        State("reactor-temp", "value"),
        State("reactor-pressure", "value"),
        State("reactor-composition", "value"),
        State("current-config", "data"),
    ],
    prevent_initial_call=True,
)
def add_reactor(
    n_clicks, reactor_id, reactor_type, temp, pressure, composition, config
):
    if not all([reactor_id, reactor_type, temp, pressure, composition]):
        return dash.no_update, True, "🔴 ERROR Please fill in all fields"

    # Check if ID already exists
    if any(comp["id"] == reactor_id for comp in config["components"]):
        return (
            dash.no_update,
            True,
            f"🔴 ERROR Component with ID {reactor_id} already exists",
        )

    # Create new reactor or reservoir
    if reactor_type == "Reservoir":
        new_reactor = {
            "id": reactor_id,
            "type": reactor_type,
            "properties": {
                "temperature": temp,
                # Reservoirs may not need pressure, but keep for consistency
                "pressure": pressure,
                "composition": composition,
            },
        }
    else:
        new_reactor = {
            "id": reactor_id,
            "type": reactor_type,
            "properties": {
                "temperature": temp,
                "pressure": pressure,
                "composition": composition,
            },
        }

    # Update config
    config["components"].append(new_reactor)
    return config, True, f"Added {reactor_type} {reactor_id}"


# Callback to add new MFC
@app.callback(
    [
        Output("current-config", "data", allow_duplicate=True),
        Output("notification-toast", "is_open", allow_duplicate=True),
        Output("notification-toast", "children", allow_duplicate=True),
    ],
    [Input("add-mfc", "n_clicks")],
    [
        State("mfc-id", "value"),
        State("mfc-source", "value"),
        State("mfc-target", "value"),
        State("mfc-flow-rate", "value"),
        State("current-config", "data"),
    ],
    prevent_initial_call=True,
)
def add_mfc(n_clicks, mfc_id, source, target, flow_rate, config):
    if not all([mfc_id, source, target, flow_rate]):
        return dash.no_update, True, "🔴 ERROR Please fill in all fields"

    # Check if connection already exists
    if any(
        conn["source"] == source and conn["target"] == target
        for conn in config["connections"]
    ):
        return (
            dash.no_update,
            True,
            f"🔴 ERROR Connection from {source} to {target} already exists",
        )

    # Create new connection
    new_connection = {
        "id": mfc_id,
        "type": "MassFlowController",
        "source": source,
        "target": target,
        "properties": {
            "flow_rate": flow_rate,
        },
    }

    # Update config with only the connection
    config["connections"].append(new_connection)
    return config, True, f"Added MFC {mfc_id} from {source} to {target}"


# Callback to handle file upload
@app.callback(
    [
        Output("current-config", "data"),
        Output("notification-toast", "is_open"),
        Output("notification-toast", "children"),
    ],
    Input("upload-config", "contents"),
    State("upload-config", "filename"),
)
def update_config(contents, filename):
    if contents is None:
        return initial_config, False, ""

    # Parse the uploaded file
    content_type, content_string = contents.split(",")
    try:
        decoded_string = base64.b64decode(content_string).decode("utf-8")
        decoded = json.loads(decoded_string)
        return decoded, True, f"✅ Configuration loaded from {filename}"
    except Exception as e:
        print(f"Error processing uploaded file: {e}")
        return dash.no_update, True, f"🔴 Error: Could not parse file {filename}."


# Callback to update the graph
@app.callback(
    [
        Output("reactor-graph", "elements"),
        Output("notification-toast", "is_open", allow_duplicate=True),
        Output("notification-toast", "children", allow_duplicate=True),
    ],
    Input("current-config", "data"),
    prevent_initial_call=True,
)
def update_graph(config):
    print("Graph updated")
    return config_to_cyto_elements(config), True, "Graph updated"


# Callback to show properties of selected element
@app.callback(
    [
        Output("properties-panel", "children"),
        Output("notification-toast", "is_open", allow_duplicate=True),
        Output("notification-toast", "children", allow_duplicate=True),
    ],
    Input("reactor-graph", "selectedNodeData"),
    Input("reactor-graph", "selectedEdgeData"),
    prevent_initial_call=True,
)
def show_properties(node_data, edge_data):
    if node_data:
        data = node_data[0]
        return (
            html.Div(
                [
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Pre(json.dumps(data["properties"], indent=2)),
                ]
            ),
            True,
            f"Viewing properties of {data['type']} {data['id']}",  # toast message
        )
    elif edge_data:
        data = edge_data[0]
        return (
            html.Div(
                [
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Pre(json.dumps(data["properties"], indent=2)),
                ]
            ),
            True,
            f"Viewing properties of {data['type']} {data['id']}",  # toast message
        )
    return html.Div("Select a node or edge to view properties"), False, ""


# Callback to run simulation and update plots
@app.callback(
    [
        Output("temperature-plot", "figure"),
        Output("pressure-plot", "figure"),
        Output("species-plot", "figure"),
        Output("notification-toast", "is_open", allow_duplicate=True),
        Output("notification-toast", "children", allow_duplicate=True),
    ],
    Input("run-simulation", "n_clicks"),
    State("current-config", "data"),
    prevent_initial_call=True,
)
def run_simulation(n_clicks, config):
    if n_clicks == 0:
        return {}, {}, {}, False, ""

    try:
        # Run the simulation
        network, results = converter.build_network(config)

        # Create temperature plot
        temp_fig = go.Figure()
        temp_fig.add_trace(
            go.Scatter(x=results["time"], y=results["temperature"], name="Temperature")
        )
        temp_fig.update_layout(
            title="Temperature vs Time",
            xaxis_title="Time (s)",
            yaxis_title="Temperature (K)",
        )

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

        return (
            temp_fig,
            press_fig,
            species_fig,
            True,
            "Simulation completed successfully",  # toast message
        )
    except Exception as e:
        return {}, {}, {}, True, str(e)


# Add callbacks to enable/disable Add buttons based on form fields
@app.callback(
    Output("add-reactor", "disabled"),
    [
        Input("reactor-id", "value"),
        Input("reactor-type", "value"),
        Input("reactor-temp", "value"),
        Input("reactor-pressure", "value"),
    ],
)
def toggle_reactor_button(reactor_id, reactor_type, temp, pressure):
    return not all([reactor_id, reactor_type, temp, pressure])


@app.callback(
    Output("add-mfc", "disabled"),
    [
        Input("mfc-id", "value"),
        Input("mfc-source", "value"),
        Input("mfc-target", "value"),
        Input("mfc-flow-rate", "value"),
    ],
)
def toggle_mfc_button(mfc_id, source, target, flow_rate):
    return not all([mfc_id, source, target, flow_rate])


# Add callback to generate default reactor ID
@app.callback(
    Output("reactor-id", "value"),
    [Input("add-reactor-modal", "is_open")],
    [State("current-config", "data")],
    prevent_initial_call=True,
)
def generate_reactor_id(is_open, config):
    if not is_open:
        return dash.no_update

    # Auto-generate reactor ID:
    # Get all existing reactor IDs
    existing_ids = [
        comp["id"]
        for comp in config["components"]
        if comp["type"] in ["IdealGasReactor", "ConstVolReactor", "ConstPReactor"]
    ]

    # Find the highest number used
    max_num = 0
    for id in existing_ids:
        if id.startswith("reactor_"):
            try:
                num = int(id.split("_")[1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                continue

    # Generate new ID
    return f"reactor_{max_num + 1}"


# Add callback to set default reactor type
@app.callback(
    Output("reactor-type", "value"),
    [Input("add-reactor-modal", "is_open")],
    prevent_initial_call=True,
)
def set_default_reactor_type(is_open):
    if is_open:
        return "IdealGasReactor"
    return dash.no_update


# Add callback to generate default MFC ID
@app.callback(
    Output("mfc-id", "value"),
    [Input("add-mfc-modal", "is_open")],
    [State("current-config", "data")],
    prevent_initial_call=True,
)
def generate_mfc_id(is_open, config):
    if not is_open:
        return dash.no_update

    # Auto-generate MFC ID:
    # Get all existing MFC IDs
    existing_ids = [
        comp["id"]
        for comp in config["components"]
        if comp["type"] == "MassFlowController"
    ]

    # Find the highest number used
    max_num = 0
    for id in existing_ids:
        if id.startswith("mfc_"):
            try:
                num = int(id.split("_")[1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                continue

    # Generate new ID
    return f"mfc_{max_num + 1}"


# Add callback to set default MFC values
@app.callback(
    [
        Output("mfc-flow-rate", "value"),
        Output("mfc-source", "value"),
        Output("mfc-target", "value"),
    ],
    [Input("add-mfc-modal", "is_open")],
    [State("current-config", "data")],
    prevent_initial_call=True,
)
def set_default_mfc_values(is_open, config):
    if not is_open:
        return dash.no_update, dash.no_update, dash.no_update

    # Get available reactor IDs for source/target
    reactor_ids = [
        comp["id"]
        for comp in config["components"]
        if comp["type"] in ["IdealGasReactor", "ConstVolReactor", "ConstPReactor"]
    ]

    # Set default source to first reactor if available
    default_source = reactor_ids[0] if reactor_ids else None

    # Set default target to second reactor if available
    default_target = reactor_ids[1] if len(reactor_ids) > 1 else None

    return 0.001, default_source, default_target


# Replace the callback that's using elementsAdded with this:


@app.callback(
    [
        Output("current-config", "data", allow_duplicate=True),
        Output("notification-toast", "is_open", allow_duplicate=True),
        Output("notification-toast", "children", allow_duplicate=True),
    ],
    [Input("edge-added-store", "data")],  # Use a store component instead
    [State("current-config", "data")],
    prevent_initial_call=True,
)
def handle_edge_creation(edge_data, config):
    if not edge_data:
        return dash.no_update, dash.no_update, dash.no_update

    # Process the edge data from the store
    source_id = edge_data.get("source")
    target_id = edge_data.get("target")

    if not source_id or not target_id:
        return dash.no_update, dash.no_update, dash.no_update

    # Check if this edge already exists in the config
    if any(
        conn["source"] == source_id and conn["target"] == target_id
        for conn in config["connections"]
    ):
        return dash.no_update, dash.no_update, dash.no_update

    # Generate unique ID for the new edge
    edge_id = f"mfc_{len(config['connections']) + 1}"

    # Add new connection to config
    config["connections"].append(
        {
            "id": edge_id,
            "source": source_id,
            "target": target_id,
            "type": "MassFlowController",
            "properties": {
                "flow_rate": 0.001  # Default flow rate
            },
        }
    )

    # Make sure to return exactly 3 values: config, is_open, children
    return config, True, f"Added connection from {source_id} to {target_id}"


# Add callback to handle edge creation from custom event
app.clientside_callback(
    """
    function(n_clicks) {
        if (!window.cy) return null;

        // Listen for the create-edge event
        if (!window._edgeListenerAdded) {
            window._edgeListenerAdded = true;
            window.addEventListener('create-edge', function(e) {
                const { source, target } = e.detail;
                // Add the edge to Cytoscape
                window.cy.add({
                    group: 'edges',
                    data: {
                        source: source,
                        target: target,
                        label: 'New Edge'  // You can customize this
                    }
                });
            });
        }
        return null;
    }
    """,
    Output("reactor-graph", "tapEdgeData"),
    Input("reactor-graph", "tapNode"),
    prevent_initial_call=True,
)

# Update toast callback to use Store as trigger
app.clientside_callback(
    """
    function(n_clicks) {
        console.log('Toast callback triggered');

        // Listen for the show-toast event
        if (!window._toastListenerAdded) {
            console.log('Setting up toast event listener');
            window._toastListenerAdded = true;
            window.addEventListener('show-toast', function(e) {
                console.log('Toast event received:', e.detail);
                const { message, type } = e.detail;
                const toast = document.getElementById('toast');
                console.log('Toast element found:', !!toast);
                if (toast) {
                    // Update toast content
                    const header = toast.querySelector('.toast-header');
                    const body = toast.querySelector('.toast-body');
                    console.log('Toast elements found:', { header: !!header, body: !!body });
                    if (header) header.textContent = type.charAt(0).toUpperCase() + type.slice(1);
                    if (body) body.textContent = message;

                    // Update toast style based on type
                    const icon = toast.querySelector('.toast-header i');
                    console.log('Icon element found:', !!icon);
                    if (icon) {
                        icon.className = 'bi bi-' + (type === 'error' ? 'exclamation-circle' :
                                                    type === 'success' ? 'check-circle' :
                                                    'info-circle');
                    }

                    // Show toast using Bootstrap's Toast
                    console.log('Creating Bootstrap Toast');
                    const bsToast = new bootstrap.Toast(toast, {
                        autohide: true,
                        delay: 3000
                    });
                    console.log('Showing toast');
                    bsToast.show();
                }
            });
        }
        return null;
    }
    """,
    Output("toast", "is_open"),
    Input("toast-trigger", "data"),
    prevent_initial_call=True,
)

# Setup client-side callback to handle edge creation
app.clientside_callback(
    """
    function(n_clicks) {
        // This is a trigger to create an initial placeholder
        return [];
    }
    """,
    Output("hidden-edge-data", "children"),
    Input("reactor-graph", "id"),
    prevent_initial_call=True,
)

# Add a clientside callback to update the store when an edge is created:
app.clientside_callback(
    """
    function(n_clicks) {
        // Initialize event listener if not done already
        if (!window.edgeEventInitialized) {
            window.edgeEventInitialized = true;

            document.addEventListener('edgeCreate', function(e) {
                if (e && e.detail) {
                    console.log('Edge creation event received:', e.detail);
                    // Update the store with new edge data
                    window.dash_clientside.no_update = false;
                    return e.detail;
                }
                return window.dash_clientside.no_update;
            });
        }

        // Initially return no update
        return window.dash_clientside.no_update;
    }
    """,
    Output("edge-added-store", "data"),
    Input("initialization-trigger", "children"),
    prevent_initial_call=True,
)

app.clientside_callback(
    """
    function(n_intervals) {
        if (window.edgehandles_setup_complete) {
            return window.dash_clientside.no_update;
        }
        const cy = (
            document.getElementById('reactor-graph') &&
            document.getElementById('reactor-graph')._cyreg &&
            document.getElementById('reactor-graph')._cyreg.cy
        );
        if (!cy || typeof cy.edgehandles !== 'function') {
            console.log("Waiting for Cytoscape and the .edgehandles() function...");
            return window.dash_clientside.no_update;
        }
        // --- One-time setup ---
        window.blocscape_edge_queue = [];
        document.addEventListener('blocscape_edge_created', e => {
            window.blocscape_edge_queue.push(e.detail);
        });
        const eh = cy.edgehandles({
            preview: true, snap: true,
            complete: (sourceNode, targetNode, addedEles) => {
                document.dispatchEvent(new CustomEvent('blocscape_edge_created', {
                    detail: { source: sourceNode.id(), target: targetNode.id(), ts: Date.now() }
                }));
            }
        });
        document.addEventListener('keydown', e => { if (e.key === 'Shift') eh.enable(); });
        document.addEventListener('keyup', e => { if (e.key === 'Shift') eh.disable(); });
        eh.disable();
        window.edgehandles_setup_complete = true;
        console.log('Edgehandles initialized.');
        return window.dash_clientside.no_update;
    }
    """,
    Output("init-dummy-output", "children"),
    Input("init-interval", "n_intervals"),
)


def run_server(debug: bool = False) -> None:
    """Run the Dash server."""
    app.run(debug=debug, host="0.0.0.0", port=8050)
