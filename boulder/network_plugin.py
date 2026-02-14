"""Network visualization plugin for Boulder.

This plugin provides a Network output pane that displays the Cantera ReactorNet
structure using the network.draw() method.
"""

import base64
from typing import Any, Dict, List, Optional

from .live_simulation import get_live_simulation
from .output_pane_plugins import OutputPaneContext, OutputPanePlugin


class NetworkPlugin(OutputPanePlugin):
    """Plugin for displaying the Cantera ReactorNet structure."""

    @property
    def plugin_id(self) -> str:
        """Unique identifier for this plugin."""
        return "network-visualization"

    @property
    def tab_label(self) -> str:
        """Label to display on the tab."""
        return "Network"

    @property
    def tab_icon(self) -> Optional[str]:
        """Optional icon for the tab."""
        return "diagram-3"

    @property
    def requires_selection(self) -> bool:
        """Whether this plugin requires a reactor/element to be selected."""
        return False

    @property
    def supported_element_types(self) -> List[str]:
        """List of element types this plugin supports."""
        return ["reactor", "connection"]

    def is_available(self, context: OutputPaneContext) -> bool:
        """Check if this plugin should be available given the current context."""
        live_sim = get_live_simulation()
        return (
            context.simulation_data is not None
            and live_sim.is_available()
            and live_sim.get_network() is not None
        )

    def create_content_data(self, context: OutputPaneContext) -> Dict[str, Any]:
        """Create JSON-serialisable content for the Network output pane."""
        live_sim = get_live_simulation()

        if not live_sim.is_available():
            return {
                "type": "error",
                "title": "Network Not Available",
                "message": (
                    "No simulation network is currently available. "
                    "Run a simulation first."
                ),
            }

        network = live_sim.get_network()
        if network is None:
            return {
                "type": "error",
                "title": "Network Not Available",
                "message": "No network found in the current simulation.",
            }

        try:
            network_image, error_message = self._generate_network_diagram(network)

            if network_image is None:
                return {
                    "type": "error",
                    "title": "Network Diagram Generation Failed",
                    "message": error_message or "Could not generate network diagram.",
                }

            return {
                "type": "image",
                "src": f"data:image/png;base64,{network_image}",
                "alt": "Reactor Network Structure",
            }

        except Exception as e:
            return {
                "type": "error",
                "title": "Error Generating Network Diagram",
                "message": f"An unexpected error occurred: {str(e)}",
            }

    def _generate_network_diagram(
        self, network: Any
    ) -> tuple[Optional[str], Optional[str]]:
        """Generate network diagram and return as base64 encoded PNG.

        Returns
        -------
        tuple
            (encoded_image, error_message) where encoded_image is base64 PNG
            or None, and error_message is the error description if generation
            failed.
        """
        try:
            import graphviz  # noqa: F401

            diagram = network.draw(
                print_state=True,
                species="X",
                graph_attr={"rankdir": "LR", "bgcolor": "white"},
                node_attr={"shape": "box", "style": "filled", "fillcolor": "lightblue"},
                edge_attr={"color": "black"},
            )

            png_data = diagram.pipe(format="png")
            encoded_image = base64.b64encode(png_data).decode("utf-8")
            return encoded_image, None

        except ImportError as e:
            return (
                None,
                f"Graphviz not available: {str(e)}. Install with: pip install graphviz",
            )
        except Exception as e:
            return None, f"Network diagram generation failed: {str(e)}"


def register_network_plugin() -> None:
    """Register the Network plugin with Boulder's output pane system."""
    from .output_pane_plugins import (
        get_output_pane_registry,
        register_output_pane_plugin,
    )

    registry = get_output_pane_registry()
    existing_ids = {p.plugin_id for p in registry.plugins}

    if "network-visualization" not in existing_ids:
        plugin = NetworkPlugin()
        register_output_pane_plugin(plugin)
