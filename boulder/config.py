"""Configuration management for the Boulder application."""

import json
import os
from typing import Any, Dict

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Global variable to control which converter to use
USE_DUAL_CONVERTER = True

# Global variable for the Cantera mechanism to use consistently across the application
CANTERA_MECHANISM = "gri30.yaml"


def load_config_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from JSON or YAML file."""
    _, ext = os.path.splitext(config_path.lower())
    
    with open(config_path, "r", encoding="utf-8") as f:
        if ext in ['.yaml', '.yml']:
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML is required to load YAML configuration files. Install with: pip install PyYAML")
            return yaml.safe_load(f)
        else:
            return json.load(f)


def get_initial_config() -> Dict[str, Any]:
    """Load the initial configuration from the sample config file.
    
    Supports both JSON and YAML formats. Prefers YAML if available.
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    
    # Try YAML first, then fallback to JSON
    yaml_path = os.path.join(data_dir, "sample_config.yaml")
    json_path = os.path.join(data_dir, "sample_config.json")
    
    if os.path.exists(yaml_path) and YAML_AVAILABLE:
        return load_config_file(yaml_path)
    elif os.path.exists(json_path):
        return load_config_file(json_path)
    else:
        raise FileNotFoundError(f"No configuration file found. Expected either {yaml_path} or {json_path}")


def get_config_from_path(config_path: str) -> Dict[str, Any]:
    """Load configuration from a specific path."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    return load_config_file(config_path)
