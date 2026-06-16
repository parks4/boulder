"""GUI Action Plugin System for Boulder.

Host packages register toolbar actions (e.g. export buttons) that appear in
the Simulate panel.  Boulder core ships with no default actions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GuiActionContext:
    """Context passed to GUI action plugins when listing or running actions."""

    config: Optional[Dict[str, Any]] = None
    config_yaml: Optional[str] = None
    filename: Optional[str] = None
    simulation_id: Optional[str] = None
    config_path: Optional[str] = None
    simulation_data: Optional[Dict[str, Any]] = None
    #: True when a valid on-disk cache entry exists for the current config.
    has_cached_result: bool = False
    #: Fingerprint hex of the cached entry, or None when no cache is available.
    cache_fingerprint: Optional[str] = None


@dataclass
class GuiActionResult:
    """File payload returned by a GUI action."""

    content: bytes
    filename: str
    media_type: str = "application/octet-stream"


class GuiActionPlugin(ABC):
    """Base class for Simulate-panel toolbar actions."""

    @property
    @abstractmethod
    def action_id(self) -> str:
        """Unique identifier for this action."""
        pass

    @property
    @abstractmethod
    def label(self) -> str:
        """Button label shown in the Simulate panel."""
        pass

    @property
    def requires_simulation(self) -> bool:
        """When True, the action is disabled until a simulation completes."""
        return False

    def is_listed(self, context: GuiActionContext) -> bool:
        """Return True when this action should appear in the Simulate panel."""
        return True

    def is_available(self, context: GuiActionContext) -> bool:
        """Return True when run() is allowed for *context*."""
        if not self.is_listed(context):
            return False
        if self.requires_simulation and not context.simulation_id:
            return False
        return True

    @abstractmethod
    def run(self, context: GuiActionContext) -> GuiActionResult:
        """Execute the action and return a downloadable file."""
        pass


@dataclass
class GuiActionRegistry:
    """Registry for GUI action plugins."""

    actions: List[GuiActionPlugin] = field(default_factory=list)

    def register(self, plugin: GuiActionPlugin) -> None:
        """Register a GUI action plugin.

        Re-registering the same action ID is a no-op so that plugins discovered
        via both entry points and ``BOULDER_PLUGINS`` do not raise on repeat.
        """
        existing_ids = {action.action_id for action in self.actions}
        if plugin.action_id in existing_ids:
            return
        self.actions.append(plugin)

    def get_listed_actions(self, context: GuiActionContext) -> List[GuiActionPlugin]:
        """Return actions that should appear in the toolbar for *context*."""
        return [action for action in self.actions if action.is_listed(context)]

    def get_available_actions(self, context: GuiActionContext) -> List[GuiActionPlugin]:
        """Return actions that may be executed for *context*."""
        return [action for action in self.actions if action.is_available(context)]

    def get_action(self, action_id: str) -> Optional[GuiActionPlugin]:
        """Return a registered action by ID, or None."""
        for action in self.actions:
            if action.action_id == action_id:
                return action
        return None


_gui_action_registry = GuiActionRegistry()


def get_gui_action_registry() -> GuiActionRegistry:
    """Return the global GUI action registry."""
    return _gui_action_registry


def register_gui_action(plugin: GuiActionPlugin) -> None:
    """Register a GUI action plugin with the global registry."""
    _gui_action_registry.register(plugin)
