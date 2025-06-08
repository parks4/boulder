"""Callback modules for the Boulder application."""

from . import graph_callbacks
from . import modal_callbacks  
from . import properties_callbacks
from . import config_callbacks
from . import simulation_callbacks
from . import notification_callbacks
from . import clientside_callbacks

def register_callbacks(app):
    """Register all callbacks with the Dash app."""
    graph_callbacks.register_callbacks(app)
    modal_callbacks.register_callbacks(app)
    properties_callbacks.register_callbacks(app) 
    config_callbacks.register_callbacks(app)
    simulation_callbacks.register_callbacks(app)
    notification_callbacks.register_callbacks(app)
    clientside_callbacks.register_callbacks(app) 