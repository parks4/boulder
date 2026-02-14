"""Output Pane Plugin System for Boulder.

This module provides the base classes and infrastructure for creating
custom output panes that can be dynamically added to Boulder's simulation results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class OutputPaneContext:
    """Context information passed to output pane plugins."""

    # Current simulation data
    simulation_data: Optional[Dict[str, Any]] = None

    # Selected element in the network (reactor, connection, etc.)
    selected_element: Optional[Dict[str, Any]] = None

    # Current configuration
    config: Optional[Dict[str, Any]] = None

    # Theme information
    theme: str = "light"

    # Simulation progress information
    progress: Optional[Any] = None


class OutputPanePlugin(ABC):
    """Base class for Output Pane plugins.

    Output Pane plugins can create custom tabs in the simulation results area
    with their own visualizations and interactions.
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique identifier for this plugin."""
        pass

    @property
    @abstractmethod
    def tab_label(self) -> str:
        """Label to display on the tab."""
        pass

    @property
    def tab_icon(self) -> Optional[str]:
        """Optional icon for the tab (Bootstrap icon class)."""
        return None

    @property
    def requires_selection(self) -> bool:
        """Whether this plugin requires a reactor/element to be selected."""
        return False

    @property
    def supported_element_types(self) -> List[str]:
        """List of element types this plugin supports."""
        return ["reactor"]

    def is_available(self, context: OutputPaneContext) -> bool:
        """Check if this plugin should be available given the current context.

        Parameters
        ----------
        context
            Current context information.

        Returns
        -------
        bool
            True if the plugin should be shown, False otherwise.
        """
        if self.requires_selection:
            if not context.selected_element:
                return False

            element_type = context.selected_element.get("type", "")
            if element_type not in self.supported_element_types:
                return False

        return True

    @abstractmethod
    def create_content_data(self, context: OutputPaneContext) -> Dict[str, Any]:
        """Create JSON-serialisable content data for this output pane.

        The returned dictionary should describe the content to render.
        Common shapes:

        - ``{"type": "image", "src": "data:image/png;base64,...", "alt": "..."}``
        - ``{"type": "text", "content": "..."}``
        - ``{"type": "error", "title": "...", "message": "..."}``

        Parameters
        ----------
        context
            Current context information.

        Returns
        -------
        dict
            JSON-serialisable content descriptor.
        """
        pass

    def get_callbacks(self) -> List[Tuple[Any, Any, Any]]:
        """Return list of callbacks this plugin needs.

        Returns
        -------
        list
            List of tuples: (outputs, inputs, callback_function).
        """
        return []

    def on_simulation_update(
        self, context: OutputPaneContext
    ) -> Optional[Dict[str, Any]]:
        """Handle simulation data update.

        Parameters
        ----------
        context
            Updated context information.

        Returns
        -------
        dict or None
            Optional dictionary of updates to apply to components.
        """
        return None


@dataclass
class OutputPaneRegistry:
    """Registry for Output Pane plugins."""

    plugins: List[OutputPanePlugin] = field(default_factory=list)

    def register(self, plugin: OutputPanePlugin) -> None:
        """Register a new output pane plugin."""
        existing_ids = {p.plugin_id for p in self.plugins}
        if plugin.plugin_id in existing_ids:
            raise ValueError(f"Plugin with ID '{plugin.plugin_id}' already registered")

        self.plugins.append(plugin)

    def get_available_plugins(
        self, context: OutputPaneContext
    ) -> List[OutputPanePlugin]:
        """Get list of plugins available for the given context."""
        return [plugin for plugin in self.plugins if plugin.is_available(context)]

    def get_plugin(self, plugin_id: str) -> Optional[OutputPanePlugin]:
        """Get a plugin by its ID."""
        for plugin in self.plugins:
            if plugin.plugin_id == plugin_id:
                return plugin
        return None


# Global registry instance
_output_pane_registry = OutputPaneRegistry()


def get_output_pane_registry() -> OutputPaneRegistry:
    """Get the global output pane registry."""
    return _output_pane_registry


def register_output_pane_plugin(plugin: OutputPanePlugin) -> None:
    """Register an output pane plugin with the global registry."""
    _output_pane_registry.register(plugin)
