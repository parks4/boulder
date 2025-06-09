"""Callback modules for the Boulder application."""

from . import (
    clientside_callbacks,
    config_callbacks,
    graph_callbacks,
    modal_callbacks,
    notification_callbacks,
    properties_callbacks,
    simulation_callbacks,
)


def register_callbacks(app) -> None:  # type: ignore
    """Register all callbacks with the Dash app."""
    graph_callbacks.register_callbacks(app)
    modal_callbacks.register_callbacks(app)
    properties_callbacks.register_callbacks(app)
    config_callbacks.register_callbacks(app)
    simulation_callbacks.register_callbacks(app)
    notification_callbacks.register_callbacks(app)
    clientside_callbacks.register_callbacks(app)
