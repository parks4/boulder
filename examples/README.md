# Boulder YAML Configuration Format

This document describes the YAML configuration format for Boulder reactor simulations. The YAML format provides a more readable and maintainable alternative to JSON configurations while maintaining full compatibility with the existing Boulder system.

## Overview

Boulder configurations describe reactor networks consisting of:
- **Components**: Individual reactors, reservoirs, and other equipment
- **Connections**: Flow connections between components (pipes, valves, controllers)
- **Metadata**: Descriptive information about the configuration
- **Simulation**: Parameters controlling the simulation execution

## Configuration Structure

### Basic Structure
```yaml
# Required sections
metadata:       # Configuration information and description
simulation:     # Simulation parameters and settings
components:     # List of reactor components
connections:    # List of flow connections between components
```

### Metadata Section
```yaml
metadata:
  name: "Configuration Name"           # Human-readable name
  description: "Brief description"     # Purpose and details
  version: "1.0"                      # Version number
```

### Simulation Section
```yaml
simulation:
  mechanism: "gri30.yaml"             # Cantera mechanism file
  time_step: 0.001                    # Integration time step (seconds)
  max_time: 10.0                      # Maximum simulation time (seconds)
  solver_type: "CVODE_BDF"            # Optional: Integration method
  rtol: 1.0e-6                        # Optional: Relative tolerance
  atol: 1.0e-9                        # Optional: Absolute tolerance
```

### Components Section
```yaml
components:
  - id: "unique_component_id"         # Unique identifier
    type: "ComponentType"             # Reactor/reservoir type
    temperature: 1000                 # Temperature (K)
    pressure: 101325                  # Optional: Pressure (Pa)
    composition: "CH4:1,O2:2,N2:7.52" # Gas composition (molar ratios)
    volume: 0.001                     # Optional: Volume (m³)
```

### Connections Section
```yaml
connections:
  - id: "unique_connection_id"        # Unique identifier
    type: "ConnectionType"            # Flow controller type
    source: "source_component_id"     # Source component ID
    target: "target_component_id"     # Target component ID
    mass_flow_rate: 0.1              # Flow rate (kg/s)
```

## Component Types

### IdealGasReactor
Main reactor for combustion simulations:
```yaml
- id: "reactor1"
  type: "IdealGasReactor"
  temperature: 1000    # Initial temperature (K)
  pressure: 101325     # Initial pressure (Pa)
  composition: "CH4:1,O2:2,N2:7.52"  # Initial composition
  volume: 0.001        # Reactor volume (m³)
```

### Reservoir
Boundary condition with fixed composition:
```yaml
- id: "inlet"
  type: "Reservoir"
  temperature: 300     # Temperature (K)
  pressure: 101325     # Optional: Pressure (Pa)
  composition: "O2:0.21,N2:0.79"     # Composition
```

## Connection Types

### MassFlowController
Controls mass flow rate between components:
```yaml
- id: "fuel_injector"
  type: "MassFlowController"
  source: "fuel_tank"
  target: "reactor1"
  mass_flow_rate: 0.05  # kg/s
```

Alternative property names:
- `flow_rate`: Alternative to `mass_flow_rate`

## Example Configurations

### 1. Basic Single Reactor (`example_config.yaml`)
Simple configuration with one reactor and one connection:
```yaml
metadata:
  name: "Basic Reactor Configuration"
  version: "1.0"

simulation:
  mechanism: "gri30.yaml"
  time_step: 0.001
  max_time: 10.0

components:
  - id: reactor1
    type: IdealGasReactor
    temperature: 1000
    pressure: 101325
    composition: "CH4:1,O2:2,N2:7.52"
    
  - id: res1
    type: Reservoir
    temperature: 300
    composition: "O2:1,N2:3.76"

connections:
  - id: mfc1
    type: MassFlowController
    source: res1
    target: reactor1
    mass_flow_rate: 0.1
```

### 2. Extended Configuration (`sample_configs2.yaml`)
Configuration with multiple components and connections:
```yaml
metadata:
  name: "Extended Reactor Configuration"
  version: "2.0"

simulation:
  mechanism: "gri30.yaml"
  time_step: 0.001
  max_time: 10.0
  solver_type: "CVODE_BDF"

components:
  - id: reactor1
    type: IdealGasReactor
    temperature: 1000
    pressure: 101325
    composition: "CH4:1,O2:2,N2:7.52"
    
  - id: res1
    type: Reservoir
    temperature: 800
    composition: "O2:1,N2:3.76"
    
  - id: downstream
    type: Reservoir
    temperature: 300
    pressure: 201325
    composition: "O2:1,N2:3.76"

connections:
  - id: mfc1
    type: MassFlowController
    source: res1
    target: reactor1
    mass_flow_rate: 0.1
    
  - id: mfc2
    type: MassFlowController
    source: reactor1
    target: downstream
    flow_rate: 0.1
```

### 3. Complex Multi-Reactor (`mix_react_streams.yaml`)
Advanced configuration with multiple reactors and complex flow patterns:
```yaml
metadata:
  name: "Mixed Reactor Streams"
  description: "Complex reactor network with multiple streams"
  version: "3.0"

simulation:
  mechanism: "gri30.yaml"
  time_step: 0.0001
  max_time: 20.0
  solver_type: "CVODE_BDF"
  rtol: 1.0e-9
  atol: 1.0e-12

components:
  # Multiple reactors with different conditions
  # Multiple supply and exhaust streams
  # See full example in mix_react_streams.yaml

connections:
  # Complex flow network connecting all components
  # See full example in mix_react_streams.yaml
```

## Usage

### Loading Configurations

#### Python API
```python
from boulder.config import load_config_file, get_config_from_path

# Load from file
config = load_config_file("examples/example_config.yaml")

# Load from specific path
config = get_config_from_path("/path/to/config.yaml")
```

#### Command Line
```bash
# The Boulder application automatically detects and loads YAML files
python run.py --config examples/example_config.yaml
```

### Validation

All configurations are automatically validated when loaded:
- **Structure validation**: Ensures required sections and fields are present
- **Reference validation**: Verifies all component references in connections are valid
- **Type validation**: Checks data types and formats
- **Normalization**: Adds default values and converts to internal format

### Error Handling

The system provides detailed error messages for configuration issues:
```
ConfigurationError: Connection 0 (mfc1) references unknown source component: 'invalid_id'
```

## Best Practices

### 1. Use Descriptive IDs
```yaml
# Good
- id: "main_combustor"
- id: "fuel_supply_tank"

# Less clear
- id: "r1"
- id: "res1"
```

### 2. Include Comments
```yaml
components:
  - id: "reactor1"
    type: "IdealGasReactor"
    temperature: 1200  # High temperature for complete combustion
    composition: "CH4:1,O2:2"  # Stoichiometric mixture
```

### 3. Group Related Components
```yaml
components:
  # Main reactors
  - id: "primary_reactor"
    # ...
  - id: "secondary_reactor"
    # ...
    
  # Supply streams  
  - id: "fuel_supply"
    # ...
  - id: "air_supply"
    # ...
```

### 4. Use Consistent Units
All values should use SI units:
- Temperature: Kelvin (K)
- Pressure: Pascals (Pa)  
- Time: Seconds (s)
- Mass flow: kg/s
- Volume: m³

### 5. Validate Before Running
```python
from boulder.config import validate_config_structure, validate_component_references

try:
    validate_config_structure(config)
    validate_component_references(config)
    print("Configuration is valid!")
except ConfigurationError as e:
    print(f"Configuration error: {e}")
```

## Migration from JSON

Existing JSON configurations can be easily converted to YAML:

### JSON Format
```json
{
  "components": [
    {
      "id": "reactor1",
      "type": "IdealGasReactor",
      "properties": {
        "temperature": 1000,
        "pressure": 101325
      }
    }
  ]
}
```

### YAML Format
```yaml
components:
  - id: reactor1
    type: IdealGasReactor
    temperature: 1000
    pressure: 101325
```

The YAML format is more concise and readable while maintaining the same structure and functionality.

## Troubleshooting

### Common Issues

1. **Invalid YAML Syntax**
   - Check indentation (use spaces, not tabs)
   - Ensure proper quoting of strings with special characters
   - Validate YAML syntax with online tools

2. **Missing Components**
   - Verify all component IDs referenced in connections exist
   - Check for typos in component and connection IDs

3. **Invalid Properties**
   - Ensure all required fields are present
   - Check data types (numbers vs strings)
   - Verify composition format: "species1:ratio1,species2:ratio2"

4. **PyYAML Not Available**
   - Install PyYAML: `pip install PyYAML`
   - Or use JSON format as fallback

### Getting Help

- Check the examples in this directory for reference configurations
- Review error messages carefully - they indicate the specific issue and location
- Use the validation functions to debug configuration problems
- Consult the Boulder documentation for component and connection types 