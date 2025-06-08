"""Configuration management for the Boulder application."""

import json
import os

# Global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Global variable to control which converter to use
USE_DUAL_CONVERTER = True


def get_initial_config():
    """Load the initial configuration from the sample config file."""
    config_path = os.path.join(os.path.dirname(__file__), "data", "sample_config.json")
    with open(config_path, "r") as f:
        return json.load(f)
