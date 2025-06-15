"""Configuration management for the Boulder application.

Supports YAML format with 🪨 STONE standard - an elegant configuration format
where component types are keys containing their properties.
"""

import os
from typing import Any, Dict

import yaml

# Global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Global variable to control which converter to use
USE_DUAL_CONVERTER = True

# Global variable for the Cantera mechanism to use consistently across the application
CANTERA_MECHANISM = "gri30.yaml"

# Theme setting: "light", "dark", or "system"
THEME = "system"


def load_config_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file with 🪨 STONE standard."""
    _, ext = os.path.splitext(config_path.lower())

    if ext not in [".yaml", ".yml"]:
        raise ValueError(
            f"Only YAML format with 🪨 STONE standard (.yaml/.yml) files are supported. "
            f"Got: {ext}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize configuration from YAML with 🪨 STONE standard to internal format.

    The 🪨 STONE standard uses component types as keys:
    - id: reactor1
      IdealGasReactor:
        temperature: 1000

    Converts to internal format:
    - id: reactor1
      type: IdealGasReactor
      properties:
        temperature: 1000
    """
    normalized = config.copy()

    # Normalize components
    if "components" in normalized:
        for component in normalized["components"]:
            if "type" not in component:
                # Find the type key (anything that's not id, metadata, etc.)
                standard_fields = {"id", "metadata"}
                type_keys = [k for k in component.keys() if k not in standard_fields]

                if type_keys:
                    type_name = type_keys[0]  # Use the first type key found
                    properties = component[type_name]

                    # Remove the type key and add type + properties
                    del component[type_name]
                    component["type"] = type_name
                    component["properties"] = (
                        properties if isinstance(properties, dict) else {}
                    )

    # Normalize connections
    if "connections" in normalized:
        for connection in normalized["connections"]:
            if "type" not in connection:
                # Find the type key (anything that's not id, source, target, metadata)
                standard_fields = {"id", "source", "target", "metadata"}
                type_keys = [k for k in connection.keys() if k not in standard_fields]

                if type_keys:
                    type_name = type_keys[0]  # Use the first type key found
                    properties = connection[type_name]

                    # Remove the type key and add type + properties
                    del connection[type_name]
                    connection["type"] = type_name
                    connection["properties"] = (
                        properties if isinstance(properties, dict) else {}
                    )

    return normalized


def get_initial_config() -> Dict[str, Any]:
    """Load the initial configuration in YAML format with 🪨 STONE standard.

    Loads from examples/example_config.yaml using the elegant 🪨 STONE standard.
    """
    # Load from examples directory (YAML with 🪨 STONE standard)
    examples_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
    stone_config_path = os.path.join(examples_dir, "example_config.yaml")

    if os.path.exists(stone_config_path):
        config = load_config_file(stone_config_path)
        return normalize_config(config)
    else:
        raise FileNotFoundError(
            f"YAML configuration file with 🪨 STONE standard not found: {stone_config_path}"
        )


def get_config_from_path(config_path: str) -> Dict[str, Any]:
    """Load configuration from a specific path."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = load_config_file(config_path)
    return normalize_config(config)


def convert_to_stone_format(config: dict) -> dict:
    """Convert internal format back to YAML with 🪨 STONE standard for file saving."""
    stone_config = {}

    # Copy metadata and simulation sections as-is
    if "metadata" in config:
        stone_config["metadata"] = config["metadata"]
    if "simulation" in config:
        stone_config["simulation"] = config["simulation"]

    # Convert components
    if "components" in config:
        stone_config["components"] = []
        for component in config["components"]:
            # Build component with id first, then type
            component_type = component.get("type", "IdealGasReactor")
            stone_component = {
                "id": component["id"],
                component_type: component.get("properties", {}),
            }
            stone_config["components"].append(stone_component)

    # Convert connections
    if "connections" in config:
        stone_config["connections"] = []
        for connection in config["connections"]:
            # Build connection with id first, then type, then source/target
            connection_type = connection.get("type", "MassFlowController")
            stone_connection = {
                "id": connection["id"],
                connection_type: connection.get("properties", {}),
                "source": connection["source"],
                "target": connection["target"],
            }
            stone_config["connections"].append(stone_connection)

    return stone_config
