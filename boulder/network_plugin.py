"""Network visualization plugin for Boulder.

This plugin provides a Network output pane that displays the Cantera ReactorNet
structure using the network.draw() method.
"""

import base64
from typing import Any, List, Optional, Union

import dash_bootstrap_components as dbc
from dash import html

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
        return "diagram-3"  # Bootstrap icon for network diagram

    @property
    def requires_selection(self) -> bool:
        """Whether this plugin requires a reactor/element to be selected."""
        return False  # Network view doesn't require selection

    @property
    def supported_element_types(self) -> List[str]:
        """List of element types this plugin supports."""
        return ["reactor", "connection"]  # Support all element types

    def is_available(self, context: OutputPaneContext) -> bool:
        """Check if this plugin should be available given the current context."""
        # Available when simulation data exists and live simulation is available
        live_sim = get_live_simulation()
        return (
            context.simulation_data is not None
            and live_sim.is_available()
            and live_sim.get_network() is not None
        )

    def create_content(
        self, context: OutputPaneContext
    ) -> Union[html.Div, dbc.Card, List[Any]]:
        """Create the content for the Network output pane."""
        live_sim = get_live_simulation()

        if not live_sim.is_available():
            return html.Div(
                [
                    html.H5("Network Not Available"),
                    html.P(
                        "No simulation network is currently available. Run a simulation first."
                    ),
                ]
            )

        network = live_sim.get_network()
        if network is None:
            return html.Div(
                [
                    html.H5("Network Not Available"),
                    html.P("No network found in the current simulation."),
                ]
            )

        try:
            # Generate the network diagram using Cantera's draw() method
            network_image, error_message = self._generate_network_diagram(network)

            if network_image is None:
                return html.Div(
                    [
                        html.H5("Network Diagram Generation Failed"),
                        html.P(error_message or "Could not generate network diagram."),
                        html.Details(
                            [
                                html.Summary("Troubleshooting"),
                                html.P("Common issues:"),
                                html.Ul(
                                    [
                                        html.Li(
                                            "Missing graphviz: pip install graphviz"
                                        ),
                                        html.Li(
                                            "Species not found in mechanism (check Error pane for details)"
                                        ),
                                        html.Li(
                                            "Network drawing not supported for this reactor type"
                                        ),
                                    ]
                                ),
                            ]
                        ),
                    ]
                )

            return dbc.Card(
                [
                    dbc.CardHeader(
                        [
                            html.H5("Reactor Network Structure", className="mb-0"),
                        ]
                    ),
                    dbc.CardBody(
                        [
                            html.Div(
                                [
                                    html.Img(
                                        src=f"data:image/png;base64,{network_image}",
                                        style={
                                            "max-width": "100%",
                                            "height": "auto",
                                            "display": "block",
                                            "margin": "0 auto",
                                        },
                                    )
                                ],
                                className="text-center",
                            ),
                        ]
                    ),
                ]
            )

        except Exception as e:
            return html.Div(
                [
                    html.H5("Error Generating Network Diagram"),
                    html.P(f"An unexpected error occurred: {str(e)}"),
                    html.Details(
                        [
                            html.Summary("Error Details"),
                            html.Pre(str(e), className="text-danger small"),
                        ]
                    ),
                ]
            )

    def _generate_network_diagram(self, network) -> tuple[Optional[str], Optional[str]]:
        """Generate network diagram and return as base64 encoded PNG.

        Returns
        -------
            tuple: (encoded_image, error_message) where encoded_image is base64 PNG or None,
                   and error_message is the error description if generation failed.
        """
        try:
            # Try to import graphviz to check if it's available
            import graphviz  # noqa: F401

            # Generate the diagram using Cantera's draw() method
            diagram = network.draw(
                print_state=True,
                species="X",  # Show mole fractions
                graph_attr={"rankdir": "LR", "bgcolor": "white"},
                node_attr={"shape": "box", "style": "filled", "fillcolor": "lightblue"},
                edge_attr={"color": "black"},
            )

            # Render to PNG format in memory
            png_data = diagram.pipe(format="png")

            # Convert to base64 for embedding in HTML
            encoded_image = base64.b64encode(png_data).decode("utf-8")
            return encoded_image, None

        except ImportError as e:
            # graphviz not available
            return (
                None,
                f"Graphviz not available: {str(e)}. Install with: pip install graphviz",
            )
        except Exception as e:
            # Other errors during diagram generation
            return None, f"Network diagram generation failed: {str(e)}"


def register_network_plugin() -> None:
    """Register the Network plugin with Boulder's output pane system."""
    from .output_pane_plugins import register_output_pane_plugin

    plugin = NetworkPlugin()
    register_output_pane_plugin(plugin)
