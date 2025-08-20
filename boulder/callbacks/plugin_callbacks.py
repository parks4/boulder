"""Callbacks for output pane plugins.

This module provides a generic plugin callback registration system.
Plugins define their own callbacks via the get_callbacks() method,
and Boulder registers them dynamically without needing to know
plugin-specific implementation details.

Plugin Callback Structure:
    Each plugin's get_callbacks() method should return a list of tuples:
    [(outputs, inputs, callback_function), ...]

    Where:
    - outputs: List of Dash Output components
    - inputs: List of Dash Input and State components
    - callback_function: The callback function to execute
"""

from typing import Any, Dict, List

import dash
from dash import Input, Output

from ..output_pane_plugins import OutputPaneContext, get_output_pane_registry


def register_callbacks(app) -> None:
    """Register plugin-related callbacks."""
    registry = get_output_pane_registry()

    # Only register callbacks if there are plugins
    if not registry.plugins:
        return

    # Callback to update plugin content when selection changes
    @app.callback(
        [
            Output(
                f"plugin-{plugin.plugin_id}-content", "children", allow_duplicate=True
            )
            for plugin in registry.plugins
        ],
        [
            Input("last-selected-element", "data"),
            Input("current-config", "data"),
            Input("theme-store", "data"),
            Input("simulation-data", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_plugin_contents(
        selected_element: Dict[str, Any],
        config: Dict[str, Any],
        theme: str,
        simulation_data: Dict[str, Any],
    ) -> List[Any]:
        """Update plugin content based on current context."""
        registry = get_output_pane_registry()

        # Create context
        context = OutputPaneContext(
            selected_element=selected_element,
            config=config,
            theme=theme,
            simulation_data=simulation_data,
        )

        # Update content for each plugin
        results = []
        for plugin in registry.plugins:
            is_available = plugin.is_available(context)

            if is_available:
                try:
                    content = plugin.create_content(context)
                    results.append(content)
                except Exception as e:
                    error_content = dash.html.Div(
                        [
                            dash.html.H5(f"Error in {plugin.tab_label} Plugin"),
                            dash.html.P(f"An error occurred: {str(e)}"),
                            dash.html.Pre(str(e), className="text-danger small"),
                        ]
                    )
                    results.append(error_content)
            else:
                # Plugin not available for current context
                unavailable_content = dash.html.Div(
                    [
                        dash.html.H5(f"{plugin.tab_label} Not Available"),
                        dash.html.P(
                            "This plugin is not available for the current selection or context."
                        ),
                    ]
                )
                results.append(unavailable_content)

        return results

    # Register any plugin-specific callbacks dynamically
    registry = get_output_pane_registry()
    for plugin in registry.plugins:
        try:
            plugin_callbacks = plugin.get_callbacks()
            for callback_spec in plugin_callbacks:
                if len(callback_spec) == 3:
                    outputs, inputs, callback_func = callback_spec
                    # Register the callback with prevent_initial_call=True for pattern-matching callbacks
                    app.callback(outputs, inputs, prevent_initial_call=True)(
                        callback_func
                    )
                    print(f"✅ Registered callback for plugin '{plugin.plugin_id}'")
                else:
                    print(
                        f"⚠️ Invalid callback specification for plugin '{plugin.plugin_id}': "
                        f"expected 3 elements, got {len(callback_spec)}"
                    )
        except Exception as e:
            print(
                f"⚠️ Could not register callbacks for plugin '{plugin.plugin_id}': {e}"
            )
            import traceback

            traceback.print_exc()
