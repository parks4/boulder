from .simulation import register_simulation_callbacks
from .config import register_config_callbacks
from .properties import register_properties_callbacks
from .reactor import register_reactor_callbacks
from .mfc import register_mfc_callbacks
from .download import register_download_callbacks

def register_all_callbacks(app):
    register_simulation_callbacks(app)
    register_config_callbacks(app)
    register_properties_callbacks(app)
    register_reactor_callbacks(app)
    register_mfc_callbacks(app)
    register_download_callbacks(app)
    # Add other register_X_callbacks(app) here as you refactor more callbacks
    pass 