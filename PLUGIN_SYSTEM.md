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

Boulder discovers plugins through two mechanisms:

1. **Environment Variable**: Set `BOULDER_PLUGINS` to a comma-separated list of module names
1. **Entry Points**: Register plugins using setuptools entry points under the `boulder.plugins` group

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

    def create_content(self, context: OutputPaneContext):
        # Return Dash components for the tab content
        return html.Div("My custom analysis content")
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

## Future Enhancements

Planned improvements to the plugin system:

- Hot-reloading of plugins during development
- Plugin configuration management
- Enhanced context information
- Plugin dependency management
- Plugin marketplace/registry
