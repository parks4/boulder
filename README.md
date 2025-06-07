# Cantera ReactorNet Visualizer

A web-based tool for visually constructing and simulating Cantera ReactorNet systems using Dash and Cytoscape.

## Features

- Interactive graph editor for creating reactor networks
- Support for various reactor types (IdealGasReactor, Reservoir)
- Support for flow devices (MassFlowController, Valve)
- Real-time property editing
- Simulation capabilities with time-series plots
- JSON configuration import/export

## Installation

1. Clone this repository
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Make sure you have Cantera installed with the GRI-Mech 3.0 mechanism

## Usage

1. Start the application:
   ```bash
   python app.py
   ```
2. Open your web browser and navigate to `http://localhost:8050`
3. Use the interface to:
   - Upload existing configurations
   - Create new reactor networks
   - Edit properties
   - Run simulations
   - View results

## Configuration Format

The application uses a JSON-based configuration format:

```json
{
  "components": [
    {
      "id": "reactor1",
      "type": "IdealGasReactor",
      "properties": {
        "temperature": 1000,
        "pressure": 101325,
        "composition": "CH4:1,O2:2,N2:7.52"
      }
    }
  ],
  "connections": [
    {
      "id": "mfc1",
      "type": "MassFlowController",
      "source": "res1",
      "target": "reactor1",
      "properties": {
        "mass_flow_rate": 0.1
      }
    }
  ]
}
```

## Supported Components

### Reactors
- IdealGasReactor
- Reservoir

### Flow Devices
- MassFlowController
- Valve

## Contributing

Feel free to submit issues and enhancement requests! 