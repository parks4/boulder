import dash
from dash import html, dcc, Input, Output, State
import dash_cytoscape as cyto
import json
import plotly.graph_objects as go
import os
from .cantera_converter import CanteraConverter
import dash_bootstrap_components as dbc

# Initialize the Dash app
app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    external_stylesheets=[dbc.themes.BOOTSTRAP],
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
                    "label": f"{comp['type']}\n{comp['id']}",
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
                    "label": f"{conn['type']}\n{conn['id']}",
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
        # File upload component
        dcc.Upload(
            id="upload-config",
            children=html.Div(
                ["Drag and Drop or ", html.A("Select a Configuration File")]
            ),
            style={
                "width": "100%",
                "height": "60px",
                "lineHeight": "60px",
                "borderWidth": "1px",
                "borderStyle": "dashed",
                "borderRadius": "5px",
                "textAlign": "center",
                "margin": "10px",
            },
        ),
        # Main content area
        html.Div(
            [
                # Left panel: Cytoscape graph
                html.Div(
                    [
                        # Add buttons for new components
                        html.Div(
                            [
                                dbc.Button(
                                    "Add Reactor",
                                    id="open-reactor-modal",
                                    color="primary",
                                    className="mr-2",
                                ),
                                dbc.Button(
                                    "Add MFC", id="open-mfc-modal", color="primary"
                                ),
                            ],
                            style={"marginBottom": "10px"},
                        ),
                        cyto.Cytoscape(
                            id="reactor-graph",
                            layout={"name": "grid"},
                            style={
                                "width": "100%",
                                "height": "80vh",
                            },
                            elements=config_to_cyto_elements(initial_config),
                            stylesheet=[
                                {
                                    "selector": "node",
                                    "style": {
                                        "label": "data(label)",
                                        "text-wrap": "wrap",
                                        "text-valign": "center",
                                        "text-halign": "center",
                                        "background-color": "#BEE",
                                        "border-width": 2,
                                        "border-color": "#888",
                                    },
                                },
                                {
                                    "selector": "edge",
                                    "style": {
                                        "label": "data(label)",
                                        "text-rotation": "autorotate",
                                        "text-margin-y": -10,
                                        "curve-style": "taxi",
                                        "target-arrow-shape": "triangle",
                                        "edge-distances": "intersection",
                                        "taxi-direction": "auto",
                                    },
                                },
                            ],
                        ),
                    ],
                    style={"width": "60%", "display": "inline-block"},
                ),
                # Right panel: Properties and simulation
                html.Div(
                    [
                        html.H3("Properties"),
                        html.Div(id="properties-panel"),
                        html.Hr(),
                        html.Button("Run Simulation", id="run-simulation", n_clicks=0),
                        html.Div(
                            [
                                dcc.Graph(id="temperature-plot"),
                                dcc.Graph(id="pressure-plot"),
                                dcc.Graph(id="species-plot"),
                            ]
                        ),
                    ],
                    style={
                        "width": "40%",
                        "display": "inline-block",
                        "verticalAlign": "top",
                    },
                ),
            ]
        ),
        # Store for the current configuration
        dcc.Store(id="current-config", data=initial_config),
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
    reactors = [
        {"label": comp["id"], "value": comp["id"]}
        for comp in config["components"]
        if comp["type"] in ["IdealGasReactor", "ConstVolReactor", "ConstPReactor"]
    ]
    return reactors, reactors


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
        State("current-config", "data"),
    ],
    prevent_initial_call=True,
)
def add_reactor(n_clicks, reactor_id, reactor_type, temp, pressure, config):
    if not all([reactor_id, reactor_type, temp, pressure]):
        return dash.no_update, True, "🔴 ERROR Please fill in all fields"

    # Check if ID already exists
    if any(comp["id"] == reactor_id for comp in config["components"]):
        return (
            dash.no_update,
            True,
            f"🔴 ERROR Component with ID {reactor_id} already exists",
        )

    # Create new reactor
    new_reactor = {
        "id": reactor_id,
        "type": reactor_type,
        "properties": {
            "temperature": temp,
            "pressure": pressure,
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
        return initial_config, False, "", ""

    # Parse the uploaded file
    content_type, content_string = contents.split(",")
    decoded = json.loads(content_string)
    return decoded, True, f"Configuration loaded from {filename}"


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
                    html.H4(f"{data['type']} Properties"),
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
                    html.H4(f"{data['type']} Properties"),
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
        return {}, {}, {}, False, "", ""

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


def run_server(debug: bool = False) -> None:
    """Run the Dash server."""
    app.run(debug=debug, host="0.0.0.0", port=8050)
