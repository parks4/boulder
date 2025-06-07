import dash
from dash import html, dcc, callback, Input, Output, State
import dash_cytoscape as cyto
import json
import plotly.graph_objects as go
import os
from .cantera_converter import CanteraConverter

# Initialize the Dash app
app = dash.Dash(__name__)

# Initialize the Cantera converter
converter = CanteraConverter()

# Load initial configuration
config_path = os.path.join(os.path.dirname(__file__), 'data', 'sample_config.json')
with open(config_path, 'r') as f:
    initial_config = json.load(f)

# Convert components to Cytoscape elements
def config_to_cyto_elements(config):
    nodes = []
    edges = []
    
    # Add nodes
    for comp in config['components']:
        nodes.append({
            'data': {
                'id': comp['id'],
                'label': f"{comp['type']}\n{comp['id']}",
                'type': comp['type'],
                'properties': comp['properties']
            }
        })
    
    # Add edges
    for conn in config['connections']:
        edges.append({
            'data': {
                'id': conn['id'],
                'source': conn['source'],
                'target': conn['target'],
                'label': f"{conn['type']}\n{conn['id']}",
                'type': conn['type'],
                'properties': conn['properties']
            }
        })
    
    return nodes + edges

# Define the layout
app.layout = html.Div([
    html.H1("Cantera ReactorNet Visualizer"),
    
    # File upload component
    dcc.Upload(
        id='upload-config',
        children=html.Div([
            'Drag and Drop or ',
            html.A('Select a Configuration File')
        ]),
        style={
            'width': '100%',
            'height': '60px',
            'lineHeight': '60px',
            'borderWidth': '1px',
            'borderStyle': 'dashed',
            'borderRadius': '5px',
            'textAlign': 'center',
            'margin': '10px'
        }
    ),
    
    # Main content area
    html.Div([
        # Left panel: Cytoscape graph
        html.Div([
            cyto.Cytoscape(
                id='reactor-graph',
                layout={'name': 'grid'},
                style={'width': '100%', 'height': '500px'},
                elements=config_to_cyto_elements(initial_config),
                stylesheet=[
                    {
                        'selector': 'node',
                        'style': {
                            'label': 'data(label)',
                            'text-wrap': 'wrap',
                            'text-valign': 'center',
                            'text-halign': 'center',
                            'background-color': '#BEE',
                            'border-width': 2,
                            'border-color': '#888'
                        }
                    },
                    {
                        'selector': 'edge',
                        'style': {
                            'label': 'data(label)',
                            'text-rotation': 'autorotate',
                            'text-margin-y': -10,
                            'curve-style': 'bezier',
                            'target-arrow-shape': 'triangle'
                        }
                    }
                ]
            )
        ], style={'width': '60%', 'display': 'inline-block'}),
        
        # Right panel: Properties and simulation
        html.Div([
            html.H3("Properties"),
            html.Div(id='properties-panel'),
            
            html.Hr(),
            
            html.Button('Run Simulation', id='run-simulation', n_clicks=0),
            
            html.Div([
                dcc.Graph(id='temperature-plot'),
                dcc.Graph(id='pressure-plot'),
                dcc.Graph(id='species-plot')
            ])
        ], style={'width': '40%', 'display': 'inline-block', 'verticalAlign': 'top'})
    ]),
    
    # Store for the current configuration
    dcc.Store(id='current-config', data=initial_config)
])

# Callback to handle file upload
@app.callback(
    Output('current-config', 'data'),
    Input('upload-config', 'contents'),
    State('upload-config', 'filename')
)
def update_config(contents, filename):
    if contents is None:
        return initial_config
    
    # Parse the uploaded file
    content_type, content_string = contents.split(',')
    decoded = json.loads(content_string)
    return decoded

# Callback to update the graph
@app.callback(
    Output('reactor-graph', 'elements'),
    Input('current-config', 'data')
)
def update_graph(config):
    return config_to_cyto_elements(config)

# Callback to show properties of selected element
@app.callback(
    Output('properties-panel', 'children'),
    Input('reactor-graph', 'selectedNodeData'),
    Input('reactor-graph', 'selectedEdgeData')
)
def show_properties(node_data, edge_data):
    if node_data:
        data = node_data[0]
        return html.Div([
            html.H4(f"{data['type']} Properties"),
            html.Pre(json.dumps(data['properties'], indent=2))
        ])
    elif edge_data:
        data = edge_data[0]
        return html.Div([
            html.H4(f"{data['type']} Properties"),
            html.Pre(json.dumps(data['properties'], indent=2))
        ])
    return html.Div("Select a node or edge to view properties")

# Callback to run simulation and update plots
@app.callback(
    [Output('temperature-plot', 'figure'),
     Output('pressure-plot', 'figure'),
     Output('species-plot', 'figure')],
    Input('run-simulation', 'n_clicks'),
    State('current-config', 'data')
)
def run_simulation(n_clicks, config):
    if n_clicks == 0:
        return {}, {}, {}
    
    # Run the simulation
    network, results = converter.build_network(config)
    
    # Create temperature plot
    temp_fig = go.Figure()
    temp_fig.add_trace(go.Scatter(
        x=results['time'],
        y=results['temperature'],
        name='Temperature'
    ))
    temp_fig.update_layout(
        title='Temperature vs Time',
        xaxis_title='Time (s)',
        yaxis_title='Temperature (K)'
    )
    
    # Create pressure plot
    press_fig = go.Figure()
    press_fig.add_trace(go.Scatter(
        x=results['time'],
        y=results['pressure'],
        name='Pressure'
    ))
    press_fig.update_layout(
        title='Pressure vs Time',
        xaxis_title='Time (s)',
        yaxis_title='Pressure (Pa)'
    )
    
    # Create species plot
    species_fig = go.Figure()
    for species, concentrations in results['species'].items():
        if max(concentrations) > 0.01:  # Only show species with significant concentration
            species_fig.add_trace(go.Scatter(
                x=results['time'],
                y=concentrations,
                name=species
            ))
    species_fig.update_layout(
        title='Species Concentrations vs Time',
        xaxis_title='Time (s)',
        yaxis_title='Mole Fraction'
    )
    
    return temp_fig, press_fig, species_fig

def run_server(debug=True):
    """Run the Dash server."""
    app.run_server(debug=debug) 