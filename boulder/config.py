"""Configuration management for the Boulder application."""

import json
import os
from typing import Any, Dict

# Global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Global variable to control which converter to use
USE_DUAL_CONVERTER = True


def get_initial_config() -> Dict[str, Any]:
    """Load the initial configuration from the sample config file."""
    config_path = os.path.join(os.path.dirname(__file__), "data", "sample_config.json")
    with open(config_path, "r") as f:
        config_data: Dict[str, Any] = json.load(f)
        return config_data
