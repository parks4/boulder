# YAML with 🪨 STONE Standard - Boulder Configuration Files

**YAML format with 🪨 STONE standard** is Boulder's elegant configuration format that makes reactor network definitions clean and intuitive.

## What is the 🪨 STONE Standard?

**🪨 STONE** stands for **Structured Type-Oriented Network Expressions** - a YAML configuration standard where component types become keys that contain their properties. This creates a visually clear hierarchy that's both human-readable and programmatically robust.

## Format Overview

### Traditional vs 🪨 STONE Standard

**Traditional YAML format:**

```yaml
components:
  - id: reactor1
    type: IdealGasReactor
    properties:
      temperature: 1000
      pressure: 101325
```

**YAML with 🪨 STONE standard:**

```yaml
components:
  - id: reactor1
    IdealGasReactor:
      temperature: 1000      # K
      pressure: 101325       # Pa
```

### Key Benefits

- **🎯 Type Prominence**: Component types are visually prominent as keys
- **🧹 Clean Structure**: No nested `properties` sections
- **📖 Better Readability**: Properties are clearly grouped under their component type
- **✅ Valid YAML**: Follows standard YAML syntax without mixed structures
- **🚀 Intuitive**: Type-properties relationship is immediately clear

## YAML with 🪨 STONE Standard Specification

### File Structure

```yaml
metadata:
  name: "Configuration Name"
  description: "Brief description"
  version: "1.0"

simulation:
  mechanism: "gri30.yaml"
  time_step: 0.001          # s
  max_time: 10.0            # s
  solver: "CVODE_BDF"
  relative_tolerance: 1.0e-6
  absolute_tolerance: 1.0e-9

components:
  - id: component_id
    ComponentType:
      property1: value1
      property2: value2
      # ... more properties

connections:
  - id: connection_id
    ConnectionType:
      property1: value1
      property2: value2
    source: source_component_id
    target: target_component_id
```

### Component Types

#### IdealGasReactor

```yaml
components:
  - id: reactor1
    IdealGasReactor:
      temperature: 1000      # K
      pressure: 101325       # Pa
      composition: "CH4:1,O2:2,N2:7.52"
      volume: 0.01           # m³ (optional)
```

#### Reservoir

```yaml
components:
  - id: inlet
    Reservoir:
      temperature: 300       # K
      pressure: 101325       # Pa (optional)
      composition: "O2:1,N2:3.76"
```

### Connection Types

#### MassFlowController

```yaml
connections:
  - id: mfc1
    MassFlowController:
      mass_flow_rate: 0.1    # kg/s
    source: inlet
    target: reactor1
```

#### Valve

```yaml
connections:
  - id: valve1
    Valve:
      valve_coeff: 1.0       # valve coefficient
    source: reactor1
    target: outlet
```

## Example Configurations

### 📁 example_config.yaml

Basic single reactor with reservoir inlet:

```yaml
metadata:
  name: "Basic Reactor Configuration"
  description: "Simple configuration with one reactor and one reservoir"
  version: "1.0"

simulation:
  mechanism: "gri30.yaml"
  time_step: 0.001
  max_time: 10.0
  solver: "CVODE_BDF"

components:
  - id: reactor1
    IdealGasReactor:
      temperature: 1000      # K
      pressure: 101325       # Pa
      composition: "CH4:1,O2:2,N2:7.52"

  - id: res1
    Reservoir:
      temperature: 300       # K
      composition: "O2:1,N2:3.76"

connections:
  - id: mfc1
    MassFlowController:
      mass_flow_rate: 0.1    # kg/s
    source: res1
    target: reactor1
```

### 📁 sample_configs2.yaml

Extended configuration with multiple components:

```yaml
metadata:
  name: "Extended Reactor Configuration"
  description: "Multi-component reactor system with different flow controllers"
  version: "2.0"

components:
  - id: reactor1
    IdealGasReactor:
      temperature: 1200      # K
      pressure: 101325       # Pa
      composition: "CH4:1,O2:2,N2:7.52"
      volume: 0.01           # m³

  - id: res1
    Reservoir:
      temperature: 300       # K
      composition: "O2:1,N2:3.76"

  - id: res2
    Reservoir:
      temperature: 350       # K
      pressure: 202650       # Pa
      composition: "CH4:1"

connections:
  - id: mfc1
    MassFlowController:
      mass_flow_rate: 0.05   # kg/s
    source: res1
    target: reactor1

  - id: mfc2
    MassFlowController:
      mass_flow_rate: 0.02   # kg/s
    source: res2
    target: reactor1
```

### 📁 mix_react_streams.yaml

Complex multi-reactor network:

```yaml
metadata:
  name: "Mixed Reactor Streams"
  description: "Complex multi-reactor network with interconnected streams"
  version: "3.0"

components:
  - id: reactor1
    IdealGasReactor:
      temperature: 1100      # K
      pressure: 101325       # Pa
      composition: "CH4:0.8,O2:1.6,N2:6.0"
      volume: 0.005          # m³

  - id: reactor2
    IdealGasReactor:
      temperature: 900       # K
      pressure: 101325       # Pa
      composition: "H2:2,O2:1,N2:3.76"
      volume: 0.008          # m³

  - id: mixer1
    IdealGasReactor:
      temperature: 400       # K
      pressure: 101325       # Pa
      composition: "N2:1"
      volume: 0.002          # m³

connections:
  - id: mfc3
    MassFlowController:
      mass_flow_rate: 0.025  # kg/s
    source: reactor1
    target: mixer1

  - id: mfc4
    MassFlowController:
      mass_flow_rate: 0.035  # kg/s
    source: mixer1
    target: reactor2
```

## Property Reference

### Common Properties

| Property | Unit | Description | Components |
|----------|------|-------------|------------|
| `temperature` | K | Gas temperature | All |
| `pressure` | Pa | Gas pressure | All |
| `composition` | - | Species mole fractions (e.g., "CH4:1,O2:2") | All |
| `volume` | m³ | Reactor volume | IdealGasReactor |
| `mass_flow_rate` | kg/s | Mass flow rate | MassFlowController |
| `valve_coeff` | - | Valve coefficient | Valve |

### Composition Format

Compositions are specified as comma-separated species:mole_fraction pairs:

```yaml
composition: "CH4:1,O2:2,N2:7.52"
# Equivalent to: 1 mol CH4, 2 mol O2, 7.52 mol N2
```

### Units and Comments

Always include units in comments for clarity:

```yaml
IdealGasReactor:
  temperature: 1000      # K
  pressure: 101325       # Pa
  mass_flow_rate: 0.1    # kg/s
  volume: 0.01           # m³
```

## Best Practices

### 🎨 Formatting

1. **Use consistent indentation** (2 spaces recommended)
1. **Include unit comments** for all physical quantities
1. **Group related components** logically
1. **Use descriptive IDs** (e.g., `fuel_inlet`, `main_reactor`)

### 🏗️ Structure

1. **Start with metadata** to describe your configuration
1. **Define simulation parameters** before components
1. **List components** before connections
1. **Order connections** by flow direction when possible

### 🔄 Composition

1. **Use standard species names** from your mechanism
1. **Normalize compositions** (they don't need to sum to 1)
1. **Include inert species** (like N2) for realistic mixtures

## Validation

YAML with 🪨 STONE standard includes automatic validation:

- ✅ **Syntax validation**: YAML parser ensures proper syntax
- ✅ **Structure validation**: Required sections and fields are checked
- ✅ **Reference validation**: All connection sources/targets must exist
- ✅ **Type validation**: Component and connection types are verified

## Getting Started

1. **Copy an example** configuration file as a starting point
1. **Modify metadata** to describe your system
1. **Update simulation parameters** for your mechanism and time scales
1. **Define your components** with appropriate properties
1. **Connect components** with flow controllers or valves
1. **Test and iterate** using Boulder's simulation interface

______________________________________________________________________

*YAML with 🪨 STONE standard makes reactor network configuration as solid as stone - reliable, clear, and built to last.*
