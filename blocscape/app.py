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

# Add a global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Cytoscape stylesheet is now set directly using the global variable
cyto_stylesheet = [
    {
        "selector": "node",
        "style": {
            "content": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "background-color": (
                "mapData(temperature, 300, 2273, deepskyblue, tomato)"
                if USE_TEMPERATURE_SCALE
                else "#BEE"
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


# Convert components to Cytoscape elements
def config_to_cyto_elements(config):
    """Convert the JSON-like configuration to two lists of Cytoscape elements:

    nodes: list of dicts, each with a 'data' key containing the node's properties
    edges: list of dicts, each with a 'data' key containing the edge's properties

    Returns:
        list: nodes + edges
    """
    nodes = []
    edges = []

    # Add nodes
    for comp in config["components"]:
        node_data = {
            "id": comp["id"],
            "label": f"{comp['id']} ({comp['type']})",
            "type": comp["type"],
            "properties": comp["properties"],
        }
        # Add temperature to top-level data for Cytoscape mapping
        temp = comp["properties"].get("temperature")
        if temp is not None:
            try:
                node_data["temperature"] = float(temp)
            except Exception:
                node_data["temperature"] = temp
        nodes.append({"data": node_data})

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
        # Store for config file name
        dcc.Store(id="config-file-name", data=""),
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
    prevent_initial_call=True,
)
def toggle_reactor_modal(n1: int, n2: int, n3: int, is_open: bool) -> tuple[bool]:
    ctx = dash.callback_context
    if not ctx.triggered:
        return (is_open,)
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "open-reactor-modal" and n1:
        return (True,)
    elif trigger == "close-reactor-modal" and n2:
        return (False,)
    elif trigger == "add-reactor" and n3:
        return (False,)
    return (is_open,)


# Callback to open/close MFC modal
@app.callback(
    Output("add-mfc-modal", "is_open"),
    [
        Input("open-mfc-modal", "n_clicks"),
        Input("close-mfc-modal", "n_clicks"),
        Input("add-mfc", "n_clicks"),
    ],
    [State("add-mfc-modal", "is_open")],
    prevent_initial_call=True,
)
def toggle_mfc_modal(n1: int, n2: int, n3: int, is_open: bool) -> tuple[bool]:
    ctx = dash.callback_context
    if not ctx.triggered:
        return (is_open,)
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "open-mfc-modal" and n1:
        return (True,)
    elif trigger == "close-mfc-modal" and n2:
        return (False,)
    elif trigger == "add-mfc" and n3:
        return (False,)
    return (is_open,)


# Callback to update MFC source/target options
@app.callback(
    [Output("mfc-source", "options"), Output("mfc-target", "options")],
    [Input("current-config", "data")],
)
def update_mfc_options(config: dict) -> tuple[list[dict], list[dict]]:
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
    n_clicks: int,
    reactor_id: str,
    reactor_type: str,
    temp: float,
    pressure: float,
    composition: str,
    config: dict,
) -> tuple[dict]:
    if not all([reactor_id, reactor_type, temp, pressure, composition]):
        return (dash.no_update,)
    if any(comp["id"] == reactor_id for comp in config["components"]):
        return (dash.no_update,)
    if reactor_type == "Reservoir":
        new_reactor = {
            "id": reactor_id,
            "type": reactor_type,
            "properties": {
                "temperature": temp,
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
    config["components"].append(new_reactor)
    return (config,)


# Callback to add new MFC
@app.callback(
    [
        Output("current-config", "data", allow_duplicate=True),
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
def add_mfc(
    n_clicks: int,
    mfc_id: str,
    source: str,
    target: str,
    flow_rate: float,
    config: dict,
) -> tuple[dict]:
    if not all([mfc_id, source, target, flow_rate]):
        return (dash.no_update,)
    if any(
        conn["source"] == source and conn["target"] == target
        for conn in config["connections"]
    ):
        return (dash.no_update,)
    new_connection = {
        "id": mfc_id,
        "type": "MassFlowController",
        "source": source,
        "target": target,
        "properties": {
            "mass_flow_rate": flow_rate,
        },
    }
    config["connections"].append(new_connection)
    return (config,)


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
                style={"display": "flex", "alignItems": "center", "marginBottom": 10},
            ),
        )
    else:
        return (
            dcc.Upload(
                id="upload-config",
                children=html.Div(["Drop or ", html.A("Select Config File")]),
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
        )


# Callback to handle config upload and delete
@app.callback(
    [
        Output("current-config", "data"),
        Output("config-file-name", "data"),
    ],
    [
        Input("upload-config", "contents"),
        Input("delete-config-file", "n_clicks"),
        Input("save-config-json-edit-btn", "n_clicks"),
    ],
    [
        State("upload-config", "filename"),
        State("config-json-edit-textarea", "value"),
        State("current-config", "data"),
    ],
    prevent_initial_call=True,
)
def handle_config_all(
    upload_contents: str,
    delete_n_clicks: int,
    save_edit_n_clicks: int,
    upload_filename: str,
    edit_text: str,
    old_config: dict,
) -> tuple:
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "upload-config" and upload_contents:
        content_type, content_string = upload_contents.split(",")
        try:
            decoded_string = base64.b64decode(content_string).decode("utf-8")
            decoded = json.loads(decoded_string)
            return decoded, upload_filename
        except Exception as e:
            print(f"Error processing uploaded file: {e}")
            return dash.no_update, ""
    elif trigger == "delete-config-file" and delete_n_clicks:
        return initial_config, ""
    elif trigger == "save-config-json-edit-btn" and save_edit_n_clicks:
        try:
            new_config = json.loads(edit_text)
            return new_config, dash.no_update
        except Exception:
            return old_config, dash.no_update
    else:
        raise dash.exceptions.PreventUpdate


# Callback to render the modal body (view or edit mode)
@app.callback(
    Output("config-json-modal-body", "children"),
    [Input("config-json-edit-mode", "data"), Input("current-config", "data")],
)
def render_config_json_modal_body(edit_mode: bool, config: dict) -> tuple:
    if edit_mode:
        return (
            html.Div(
                [
                    dcc.Textarea(
                        id="config-json-edit-textarea",
                        value=json.dumps(config, indent=2),
                        style={
                            "width": "100%",
                            "height": "60vh",
                            "fontFamily": "monospace",
                        },
                    ),
                ]
            ),
        )
    else:
        return (
            html.Pre(
                json.dumps(config, indent=2),
                style={"maxHeight": "60vh", "overflowY": "auto"},
            ),
        )


# Callback to handle edit mode switching
@app.callback(
    Output("config-json-edit-mode", "data"),
    [
        Input("edit-config-json-btn", "n_clicks"),
        Input("cancel-config-json-edit-btn", "n_clicks"),
        Input("save-config-json-edit-btn", "n_clicks"),
    ],
    [State("config-json-edit-mode", "data")],
    prevent_initial_call=True,
)
def toggle_config_json_edit_mode(
    edit_n: int,
    cancel_n: int,
    save_n: int,
    edit_mode: bool,
) -> bool:
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "edit-config-json-btn":
        return True
    elif trigger in ("cancel-config-json-edit-btn", "save-config-json-edit-btn"):
        return False
    return edit_mode


# Callback to download config as JSON
@app.callback(
    Output("download-config-json", "data"),
    [Input("save-config-json-btn", "n_clicks")],
    [State("current-config", "data")],
    prevent_initial_call=True,
)
def download_config_json(n: int, config: dict):
    if n:
        return dict(content=json.dumps(config, indent=2), filename="config.json")
    return dash.no_update


# Callback to update the graph
@app.callback(
    [
        Output("reactor-graph", "elements"),
    ],
    Input("current-config", "data"),
    prevent_initial_call=True,
)
def update_graph(config: dict) -> tuple:
    return (config_to_cyto_elements(config),)


# Callback to show properties of selected element (editable)
@app.callback(
    Output("properties-panel", "children"),
    [
        Input("last-selected-element", "data"),
        Input("properties-edit-mode", "data"),
        Input("current-config", "data"),
    ],
    prevent_initial_call=True,
)
def show_properties_editable(last_selected, edit_mode, config):
    node_data = None
    edge_data = None
    if last_selected and last_selected.get("type") == "node":
        node_id = last_selected["data"]["id"]
        # Find the latest node data from config
        for comp in config["components"]:
            if comp["id"] == node_id:
                node_data = [comp]
                break
    elif last_selected and last_selected.get("type") == "edge":
        edge_id = last_selected["data"]["id"]
        for conn in config["connections"]:
            if conn["id"] == edge_id:
                edge_data = [conn]
                break

    def label_with_unit(k):
        if k == "pressure":
            return f"{k} (Pa)"
        elif k == "composition":
            return f"{k} (%mol)"
        elif k == "temperature":
            return f"{k} (K)"
        return k

    if node_data:
        data = node_data[0]
        properties = data["properties"]
        if edit_mode:
            fields = [
                dbc.Row(
                    [
                        dbc.Col(html.Label(label_with_unit(k)), width=6),
                        dbc.Col(
                            dcc.Input(
                                id={"type": "prop-edit", "prop": k},
                                value=str(v),
                                type="text",
                                style={"width": "100%"},
                            ),
                            width=6,
                        ),
                    ],
                    className="mb-2",
                )
                for k, v in properties.items()
            ]
            return html.Div(
                [
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row(
                        [
                            dbc.Col(
                                html.Button(
                                    "Save",
                                    id="properties-save-btn",
                                    n_clicks=0,
                                    style={"display": "inline-block"},
                                ),
                                width="auto",
                            ),
                            dbc.Col(
                                html.Button(
                                    "Edit",
                                    id="properties-edit-btn",
                                    n_clicks=0,
                                    style={"display": "none"},
                                ),
                                width="auto",
                            ),
                        ],
                        className="mt-3",
                    ),
                ]
            )
        else:
            fields = [
                dbc.Row(
                    [
                        dbc.Col(html.Label(label_with_unit(k)), width=6),
                        dbc.Col(
                            html.Div(str(v), style={"wordBreak": "break-all"}), width=6
                        ),
                    ],
                    className="mb-2",
                )
                for k, v in properties.items()
            ]
            return html.Div(
                [
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row(
                        [
                            dbc.Col(
                                html.Button(
                                    "Save",
                                    id="properties-save-btn",
                                    n_clicks=0,
                                    style={"display": "none"},
                                ),
                                width="auto",
                            ),
                            dbc.Col(
                                html.Button(
                                    "Edit",
                                    id="properties-edit-btn",
                                    n_clicks=0,
                                    style={"display": "inline-block"},
                                ),
                                width="auto",
                            ),
                        ],
                        className="mt-3",
                    ),
                ]
            )
    elif edge_data:
        data = edge_data[0]
        properties = data["properties"]
        if edit_mode:
            fields = [
                dbc.Row(
                    [
                        dbc.Col(html.Label(label_with_unit(k)), width=5),
                        dbc.Col(
                            dcc.Input(
                                id={"type": "prop-edit", "prop": k},
                                value=str(v),
                                type="text",
                                style={"width": "100%"},
                            ),
                            width=7,
                        ),
                    ],
                    className="mb-2",
                )
                for k, v in properties.items()
            ]
            return html.Div(
                [
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row(
                        [
                            dbc.Col(
                                html.Button(
                                    "Save",
                                    id="properties-save-btn",
                                    n_clicks=0,
                                    style={"display": "inline-block"},
                                ),
                                width="auto",
                            ),
                            dbc.Col(
                                html.Button(
                                    "Edit",
                                    id="properties-edit-btn",
                                    n_clicks=0,
                                    style={"display": "none"},
                                ),
                                width="auto",
                            ),
                        ],
                        className="mt-3",
                    ),
                ]
            )
        else:
            fields = [
                dbc.Row(
                    [
                        dbc.Col(html.Label(label_with_unit(k)), width=5),
                        dbc.Col(
                            html.Div(str(v), style={"wordBreak": "break-all"}), width=7
                        ),
                    ],
                    className="mb-2",
                )
                for k, v in properties.items()
            ]
            return html.Div(
                [
                    html.H4(f"{data['id']} ({data['type']})"),
                    html.Div(fields),
                    dbc.Row(
                        [
                            dbc.Col(
                                html.Button(
                                    "Save",
                                    id="properties-save-btn",
                                    n_clicks=0,
                                    style={"display": "none"},
                                ),
                                width="auto",
                            ),
                            dbc.Col(
                                html.Button(
                                    "Edit",
                                    id="properties-edit-btn",
                                    n_clicks=0,
                                    style={"display": "inline-block"},
                                ),
                                width="auto",
                            ),
                        ],
                        className="mt-3",
                    ),
                ]
            )
    return html.Div("Select a node or edge to view properties")


# Callback to toggle properties edit mode
@app.callback(
    Output("properties-edit-mode", "data"),
    [
        Input("properties-edit-btn", "n_clicks"),
        Input("properties-save-btn", "n_clicks"),
    ],
    [State("properties-edit-mode", "data")],
    prevent_initial_call=True,
)
def toggle_properties_edit_mode(edit_n, save_n, edit_mode):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "properties-edit-btn" and edit_n:
        return True
    elif trigger == "properties-save-btn" and save_n:
        return False
    return edit_mode


# Callback to save edited properties
@app.callback(
    Output("current-config", "data", allow_duplicate=True),
    [Input("properties-save-btn", "n_clicks")],
    [
        State("reactor-graph", "selectedNodeData"),
        State("reactor-graph", "selectedEdgeData"),
        State("current-config", "data"),
        State({"type": "prop-edit", "prop": dash.ALL}, "value"),
        State({"type": "prop-edit", "prop": dash.ALL}, "id"),
    ],
    prevent_initial_call=True,
)
def save_properties(n_clicks, node_data, edge_data, config, values, ids):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    if node_data:
        data = node_data[0]
        comp_id = data["id"]
        for comp in config["components"]:
            if comp["id"] == comp_id:
                for v, i in zip(values, ids):
                    key = i["prop"]
                    # Convert to float if key is temperature or pressure
                    if key in ("temperature", "pressure"):
                        try:
                            comp["properties"][key] = float(v)
                        except Exception:
                            comp["properties"][key] = v
                    else:
                        comp["properties"][key] = v
                break
    elif edge_data:
        data = edge_data[0]
        conn_id = data["id"]
        for conn in config["connections"]:
            if conn["id"] == conn_id:
                for v, i in zip(values, ids):
                    key = i["prop"]
                    # Map 'flow_rate' to 'mass_flow_rate' for MassFlowController
                    if conn["type"] == "MassFlowController" and key == "flow_rate":
                        try:
                            conn["properties"]["mass_flow_rate"] = float(v)
                        except Exception:
                            conn["properties"]["mass_flow_rate"] = v
                        # Optionally remove old key
                        if "flow_rate" in conn["properties"]:
                            del conn["properties"]["flow_rate"]
                    else:
                        conn["properties"][key] = v
                break
    return config


# Callback to run simulation and update plots
@app.callback(
    [
        Output("temperature-plot", "figure"),
        Output("pressure-plot", "figure"),
        Output("species-plot", "figure"),
    ],
    Input("run-simulation", "n_clicks"),
    State("current-config", "data"),
    prevent_initial_call=True,
)
def run_simulation(n_clicks: int, config: dict) -> tuple:
    if n_clicks == 0:
        return {}, {}, {}

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
        )
    except Exception:
        return {}, {}, {}


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
def toggle_reactor_button(
    reactor_id: str, reactor_type: str, temp: float, pressure: float
) -> bool:
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
def toggle_mfc_button(mfc_id: str, source: str, target: str, flow_rate: float) -> bool:
    return not all([mfc_id, source, target, flow_rate])


# Add callback to generate default reactor ID
@app.callback(
    Output("reactor-id", "value"),
    [Input("add-reactor-modal", "is_open")],
    [State("current-config", "data")],
    prevent_initial_call=True,
)
def generate_reactor_id(is_open: bool, config: dict) -> str:
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
def set_default_reactor_type(is_open: bool) -> str:
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
def generate_mfc_id(is_open: bool, config: dict) -> str:
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
def set_default_mfc_values(is_open: bool, config: dict) -> tuple:
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
    ],
    [Input("edge-added-store", "data")],  # Use a store component instead
    [State("current-config", "data")],
    prevent_initial_call=True,
)
def handle_edge_creation(edge_data: dict, config: dict) -> tuple:
    if not edge_data:
        return (dash.no_update,)

    # Process the edge data from the store
    source_id = edge_data.get("source")
    target_id = edge_data.get("target")

    if not source_id or not target_id:
        return (dash.no_update,)

    # Check if this edge already exists in the config
    if any(
        conn["source"] == source_id and conn["target"] == target_id
        for conn in config["connections"]
    ):
        return (dash.no_update,)

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
                "mass_flow_rate": 0.001  # Default flow rate
            },
        }
    )

    return (config,)


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


@app.callback(
    [
        Output("notification-toast", "is_open"),
        Output("notification-toast", "children"),
        Output("notification-toast", "style"),
    ],
    [
        Input("add-reactor", "n_clicks"),
        Input("add-mfc", "n_clicks"),
        Input("upload-config", "contents"),
        Input("delete-config-file", "n_clicks"),
        Input("save-config-json-edit-btn", "n_clicks"),
        Input("edge-added-store", "data"),
        Input("run-simulation", "n_clicks"),
        Input("reactor-graph", "selectedNodeData"),
        Input("reactor-graph", "selectedEdgeData"),
        Input("current-config", "data"),
    ],
    [
        State("reactor-id", "value"),
        State("reactor-type", "value"),
        State("reactor-temp", "value"),
        State("reactor-pressure", "value"),
        State("reactor-composition", "value"),
        State("mfc-id", "value"),
        State("mfc-source", "value"),
        State("mfc-target", "value"),
        State("mfc-flow-rate", "value"),
        State("upload-config", "filename"),
        State("config-json-edit-textarea", "value"),
        State("current-config", "data"),
        State("edge-added-store", "data"),
        State("run-simulation", "n_clicks"),
        State("reactor-graph", "selectedNodeData"),
        State("reactor-graph", "selectedEdgeData"),
    ],
    prevent_initial_call=True,
)
def notification_handler(
    add_reactor_click: int,
    add_mfc_click: int,
    upload_contents: str,
    delete_config_click: int,
    save_edit_click: int,
    edge_data: dict,
    run_sim_click: int,
    selected_node: list,
    selected_edge: list,
    config_data: dict,
    reactor_id: str,
    reactor_type: str,
    reactor_temp: float,
    reactor_pressure: float,
    reactor_composition: str,
    mfc_id: str,
    mfc_source: str,
    mfc_target: str,
    mfc_flow_rate: float,
    upload_filename: str,
    edit_text: str,
    config: dict,
    edge_store: dict,
    run_sim_n: int,
    node_data: list,
    edge_data_selected: list,
):
    """Handle the various events that can trigger the notification toast.

    Notification toast is used to display messages to the user, they disappear after 1.5 seconds.
    """
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]

    # Add Reactor
    if trigger == "add-reactor" and add_reactor_click:
        if not all(
            [
                reactor_id,
                reactor_type,
                reactor_temp,
                reactor_pressure,
                reactor_composition,
            ]
        ):
            return (
                True,
                "🔴 ERROR Please fill in all fields",
                {
                    "position": "fixed",
                    "top": 66,
                    "right": 10,
                    "width": 350,
                    "backgroundColor": "#dc3545",
                    "color": "white",
                },
            )
        if any(comp["id"] == reactor_id for comp in config["components"]):
            return (
                True,
                f"🔴 ERROR Component with ID {reactor_id} already exists",
                {
                    "position": "fixed",
                    "top": 66,
                    "right": 10,
                    "width": 350,
                    "backgroundColor": "#dc3545",
                    "color": "white",
                },
            )
        return (
            True,
            f"Added {reactor_type} {reactor_id}",
            {"position": "fixed", "top": 66, "right": 10, "width": 350},
        )

    # Add MFC
    if trigger == "add-mfc" and add_mfc_click:
        if not all([mfc_id, mfc_source, mfc_target, mfc_flow_rate]):
            return (
                True,
                "🔴 ERROR Please fill in all fields",
                {
                    "position": "fixed",
                    "top": 66,
                    "right": 10,
                    "width": 350,
                    "backgroundColor": "#dc3545",
                    "color": "white",
                },
            )
        if any(
            conn["source"] == mfc_source and conn["target"] == mfc_target
            for conn in config["connections"]
        ):
            return (
                True,
                f"🔴 ERROR Connection from {mfc_source} to {mfc_target} already exists",
                {
                    "position": "fixed",
                    "top": 66,
                    "right": 10,
                    "width": 350,
                    "backgroundColor": "#dc3545",
                    "color": "white",
                },
            )
        return (
            True,
            f"Added MFC {mfc_id} from {mfc_source} to {mfc_target}",
            {"position": "fixed", "top": 66, "right": 10, "width": 350},
        )

    # Config upload
    if trigger == "upload-config" and upload_contents:
        try:
            content_type, content_string = upload_contents.split(",")
            decoded_string = base64.b64decode(content_string).decode("utf-8")
            json.loads(decoded_string)
            return (
                True,
                f"✅ Configuration loaded from {upload_filename}",
                {"position": "fixed", "top": 66, "right": 10, "width": 350},
            )
        except Exception:
            return (
                True,
                f"🔴 Error: Could not parse file {upload_filename}.",
                {
                    "position": "fixed",
                    "top": 66,
                    "right": 10,
                    "width": 350,
                    "backgroundColor": "#dc3545",
                    "color": "white",
                },
            )

    # Config delete
    if trigger == "delete-config-file" and delete_config_click:
        return (
            True,
            "Config file removed.",
            {"position": "fixed", "top": 66, "right": 10, "width": 350},
        )

    # Config edit
    if trigger == "save-config-json-edit-btn" and save_edit_click:
        try:
            json.loads(edit_text)
            return (
                True,
                "✅ Configuration updated from editor.",
                {"position": "fixed", "top": 66, "right": 10, "width": 350},
            )
        except Exception as e:
            return (
                True,
                f"🔴 Error: Invalid JSON. {e}",
                {
                    "position": "fixed",
                    "top": 66,
                    "right": 10,
                    "width": 350,
                    "backgroundColor": "#dc3545",
                    "color": "white",
                },
            )

    # Edge creation
    if trigger == "edge-added-store" and edge_data:
        if edge_data and edge_data.get("source") and edge_data.get("target"):
            return (
                True,
                f"Added connection from {edge_data['source']} to {edge_data['target']}",
                {"position": "fixed", "top": 66, "right": 10, "width": 350},
            )

    # Run simulation
    if trigger == "run-simulation" and run_sim_click:
        return (
            True,
            "Simulation completed successfully",
            {"position": "fixed", "top": 66, "right": 10, "width": 350},
        )

    # Show properties
    if trigger == "reactor-graph" and (selected_node or selected_edge):
        data = (
            (selected_node or selected_edge)[0]
            if (selected_node or selected_edge)
            else None
        )
        if data:
            return (
                True,
                f"Viewing properties of {data['type']} {data['id']}",
                {"position": "fixed", "top": 66, "right": 10, "width": 350},
            )

    # Graph update
    if trigger == "current-config":
        return (
            True,
            "Graph updated",
            {"position": "fixed", "top": 66, "right": 10, "width": 350},
        )

    return False, "", {"position": "fixed", "top": 66, "right": 10, "width": 350}


@app.callback(
    Output("config-json-modal", "is_open"),
    [
        Input("config-file-name-span", "n_clicks"),
        Input("close-config-json-modal", "n_clicks"),
    ],
    [State("config-json-modal", "is_open")],
    prevent_initial_call=True,
)
def toggle_config_json_modal(open_n: int, close_n: int, is_open: bool) -> bool:
    """Toggle the configuration JSON modal.
    The modal is used to edit the configuration JSON file.
    """
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "config-file-name-span" and open_n:
        return True
    elif trigger == "close-config-json-modal" and close_n:
        return False
    return is_open


# Add a callback to control button visibility
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
def set_json_modal_button_visibility(edit_mode: bool):
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


# Add a callback to update last-selected-element on selection
@app.callback(
    Output("last-selected-element", "data"),
    [
        Input("reactor-graph", "selectedNodeData"),
        Input("reactor-graph", "selectedEdgeData"),
    ],
    prevent_initial_call=True,
)
def update_last_selected(node_data, edge_data):
    if node_data:
        return {"type": "node", "data": node_data[0]}
    elif edge_data:
        return {"type": "edge", "data": edge_data[0]}
    return {}


# After Save, re-trigger last-selected-element to force update
@app.callback(
    Output("last-selected-element", "data", allow_duplicate=True),
    [Input("properties-save-btn", "n_clicks")],
    [State("last-selected-element", "data")],
    prevent_initial_call=True,
)
def retrigger_last_selected(n_clicks, last_selected):
    if n_clicks:
        return last_selected
    raise dash.exceptions.PreventUpdate


def run_server(debug: bool = False) -> None:
    """Run the Dash server."""
    app.run(debug=debug, host="0.0.0.0", port=8050)
