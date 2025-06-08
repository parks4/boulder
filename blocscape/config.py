"""
Application configuration settings for Blocscape.
This file contains global configuration variables that can be modified to change application behavior.
"""

# Simulation settings
USE_DUAL_CONVERTER = True  # Whether to use the dual converter for simulation

# File settings
MAX_UPLOAD_SIZE = 1024 * 1024  # Maximum file upload size in bytes (1MB)

# UI settings
DEFAULT_THEME = "BOOTSTRAP"  # Default theme for the application
USE_TEMPERATURE_COLORING = True  # Whether to color nodes based on temperature (True) or use fixed color (False) 