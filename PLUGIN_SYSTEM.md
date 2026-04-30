# Boulder Output Pane Plugin System

Boulder now supports a plugin system for creating custom Output Panes that can be dynamically added to the simulation results area.

## Overview

The plugin system allows external packages (like Bloc) to create custom visualization and analysis panes that integrate seamlessly with Boulder's interface. Plugins can:

- Create custom tabs in the simulation results area
- Access current simulation data, configuration, and selected elements
- Provide interactive controls and visualizations
- Register custom callbacks for dynamic behavior

## Plugin Architecture

### Base Classes

- `OutputPanePlugin`: Abstract base class for all output pane plugins
- `OutputPaneContext`: Context object containing current state information
- `OutputPaneRegistry`: Registry for managing plugin instances

### Plugin Discovery

Boulder discovers plugins through two complementary mechanisms. Both run at
startup and *add* to the same `BoulderPlugins` container; they are not
alternatives but different audiences:

1. **Entry points (`boulder.plugins`)** — the canonical path for **packaged**
   plugins distributed via `pip`. Register your `register_plugins(plugins)`
   callable in `pyproject.toml`:

   ```toml
   [project.entry-points."boulder.plugins"]
   my_plugin = "my_package.boulder_plugins:register_plugins"
   ```

   This is how the bundled spatial output pane plugin is picked up.

1. **`BOULDER_PLUGINS` environment variable** — a comma- or semicolon-separated
   list of module names for **local / unpackaged / per-project** plugin
   development. Boulder imports each module and calls its `register_plugins`.
   `boulder/cli.py` and `boulder/api/main.py` automatically load a `.env` file
   next to the repo so that per-project plugins can be wired without
   reinstalling anything:

   ```bash
   # .env at the repo root
   BOULDER_PLUGINS=my_local_pkg.boulder_plugins
   ```

### Inspecting what loaded

Run

```bash
boulder plugins list
```

to print the plugins loaded from each discovery path and the counts of
registered reactor builders, connection builders, post-build hooks, output
panes, and summary builders.

### Optional: declarative schema for a reactor kind

Plugins registering new reactor kinds can opt into a Pydantic schema so that
`boulder validate <yaml>` and `boulder describe <kind>` can check YAML files
and render UI property panes without running Cantera. Use the helper
`boulder.register_reactor_builder`:

```python
from pydantic import BaseModel, Field
from boulder import register_reactor_builder

class MyReactorSchema(BaseModel):
    length:   float = Field(...,  description="[m] Reactor length")
    diameter: float = Field(...,  description="[m] Reactor diameter")

def register_plugins(plugins):
    register_reactor_builder(
        plugins,
        kind="MyReactor",
        builder=_build_my_reactor,
        network_class=MyReactorNet,
        schema=MyReactorSchema,
        categories={
            "inputs":  {"GEOMETRY": ["length", "diameter"]},
            "outputs": {"OUTLET": ["T_outlet_K"]},
        },
        default_constraints=[
            {"key": "T_outlet_K", "description": "Max outlet T",
             "operator": "<", "threshold": 1800.0},
        ],
    )
```

Plugins that still write directly to `plugins.reactor_builders[kind] = fn`
keep working exactly as before; they simply do not benefit from schema-based
validation.

## Creating a Plugin

### 1. Implement the Plugin Class

```python
from boulder.output_pane_plugins import OutputPanePlugin, OutputPaneContext

class MyPlugin(OutputPanePlugin):
    @property
    def plugin_id(self) -> str:
        return "my_plugin"

    @property
    def tab_label(self) -> str:
        return "My Analysis"

    @property
    def requires_selection(self) -> bool:
        return True  # Requires a reactor/element to be selected

    def is_available(self, context: OutputPaneContext) -> bool:
        # Check if plugin should be shown for current context
        return context.selected_element is not None

    def create_content_data(self, context: OutputPaneContext):
        # Return JSON-serialisable data for the tab content
        return {"type": "text", "content": "My custom analysis content"}
```

### 2. Register the Plugin

Create a registration function:

```python
def register_plugins(plugins):
    """Called by Boulder's plugin discovery system."""
    from boulder.output_pane_plugins import register_output_pane_plugin

    plugin = MyPlugin()
    register_output_pane_plugin(plugin)
```

### 3. Enable Plugin Discovery

Set the environment variable:

```bash
export BOULDER_PLUGINS=my_package.register_plugins
```

Or use entry points in `setup.py`:

```python
setup(
    # ... other setup parameters
    entry_points={
        'boulder.plugins': [
            'my_plugin = my_package:register_plugins',
        ],
    },
)
```

## Spatial Output Pane Plugin Example

The Spatial Output Pane plugin (implemented in Bloc) demonstrates the plugin system:

### Features

- Analyzes reactors with `length` properties
- Converts length to residence time using flow velocity
- Creates spatial distributions of temperature, pressure, and species
- Provides interactive controls for simulation parameters

### Usage

1. Load a configuration with a reactor that has a `length` property
1. Select the reactor in the Network pane
1. The "Spatial" tab will appear in the simulation results
1. Configure spatial analysis parameters and generate distributions

### Example Configuration

```yaml
nodes:
  - id: tubular_reactor
    IdealGasReactor:
      temperature: 800  # °C
      pressure: 1.0  # atm
      composition: "CH4:1,O2:2,N2:7.52"
      volume: 0.001  # m³
      length: 2.0  # m - Enables spatial analysis!
```

### Enabling the Spatial Plugin

The Spatial plugin is automatically discovered via entry points when Bloc is installed. No manual configuration is needed!

Simply run Boulder as usual. The Spatial tab will appear automatically when a reactor with a length property is selected.

## Plugin Context

The `OutputPaneContext` object provides plugins with access to:

- `simulation_data`: Current simulation results
- `selected_element`: Currently selected network element
- `config`: Current configuration
- `theme`: UI theme ("light" or "dark")
- `progress`: Simulation progress information

## Best Practices

1. **Graceful Degradation**: Handle missing dependencies gracefully
1. **Error Handling**: Wrap plugin code in try-catch blocks
1. **Performance**: Avoid heavy computations in `is_available()`
1. **UI Consistency**: Use Bootstrap components for consistent styling
1. **Documentation**: Document plugin requirements and usage

## Troubleshooting

- **Plugin not appearing**: Check that `BOULDER_PLUGINS` is set correctly
- **Import errors**: Ensure all dependencies are installed
- **Callback conflicts**: Use unique component IDs in your plugin
- **Performance issues**: Profile plugin code and optimize heavy operations

## Composite Reactors — `ReactorUnfolder`

Some reactor kinds are _composite_: they conceptually own satellite Cantera
objects such as an ambient `Reservoir` and a radial-loss `Wall`. The
`ReactorUnfolder` API lets a plugin declare these satellites **at config
normalisation time**, so they appear as first-class nodes/connections in:

- the Cytoscape IDE graph (`/api/graph/elements`),
- the staged solver's per-group networks,
- the `ct.ReactorNet` topology (enabling the standard `draw()` without custom
  overrides).

### Registering an unfolder

```python
from boulder import register_reactor_unfolder

def _my_unfolder(node):
    rid = node["id"]
    group = node.get("group") or (node.get("properties") or {}).get("group")
    mech  = node.get("mechanism") or (node.get("properties") or {}).get("mechanism")
    ambient_props = {
        "temperature": 298.15, "pressure": 101325.0, "composition": "N2:1",
        **({"group": group} if group else {}),
        **({"mechanism": mech} if mech else {}),
    }
    return {
        "nodes": [{
            "id": f"{rid}_ambient", "type": "Reservoir",
            "properties": ambient_props,
            **({"group": group} if group else {}),
        }],
        "connections": [{
            "id": f"{rid}_loss_wall", "type": "Wall",
            "source": f"{rid}_ambient", "target": rid,
            "properties": {"area": 1.0},
        }],
    }

def register_plugins(plugins):
    register_reactor_unfolder(plugins, "MyCompositeReactor", _my_unfolder)
```

### Design rules

1. **Parent-prefixed ids**: generated ids must start with `{node_id}_` to
   prevent collisions when multiple instances of the same kind appear in a YAML.
1. **Collision-intolerant**: if the config already contains an id emitted by
   the unfolder, the entries must be byte-identical or `ValueError` is raised.
1. **Adiabatic / conditional satellites**: return `{}` to suppress satellites
   for specific configurations (e.g. `adiabatic: true`).
1. **Group + mechanism propagation**: copy both `node["group"]` (top-level) and
   `node["properties"]["group"]` to each emitted node so Cytoscape assigns
   the satellite to the correct stage group. Copy `mechanism` into
   `properties.mechanism` of emitted Reservoirs so the staged solver uses the
   same Cantera `Solution` as the parent.
1. **Post-build hooks still apply**: the unfolder produces STONE config entries;
   the post-build hook then looks up the built `ct.Wall` / `ct.Reservoir` in
   `converter.walls` / `converter.reactors` (by the deterministic ids above)
   and stores them as `reactor._loss_wall` / `reactor._ambient_reservoir` for
   physics use.

### Relationship to `expand_port_shortcuts`

`expand_composite_kinds` runs **after** `expand_port_shortcuts` in
`normalize_config`, so inline `inlet:`/`outlet:` ports on the parent node
have already been converted to real connections before the unfolder is called.
The two passes together form Boulder's full config pre-processing pipeline:

```
STONE normalisation → expand_port_shortcuts → expand_composite_kinds
  → _sort_connections_by_master → synthesize_default_group
```

## Future Enhancements

Planned improvements to the plugin system:

- Hot-reloading of plugins during development
- Plugin configuration management
- Enhanced context information
- Plugin dependency management
- Plugin marketplace/registry
