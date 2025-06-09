"""Configuration management for the Boulder application."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Setup logging for configuration module
logger = logging.getLogger(__name__)

# Global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Global variable to control which converter to use
USE_DUAL_CONVERTER = True

# Global variable for the Cantera mechanism to use consistently across the application
CANTERA_MECHANISM = "gri30.yaml"


class ConfigurationError(Exception):
    """Custom exception for configuration-related errors."""

    pass


def validate_config_structure(config: Dict[str, Any]) -> bool:
    """
    Validate the basic structure of a configuration dictionary.

    Args:
        config: Configuration dictionary to validate

    Returns
    -------
        bool: True if valid, raises ConfigurationError if invalid

    Raises
    ------
        ConfigurationError: If the configuration structure is invalid
    """
    required_sections = ["components", "connections"]

    # Check for required sections
    for section in required_sections:
        if section not in config:
            raise ConfigurationError(f"Missing required section: '{section}'")

    # Validate components structure
    if not isinstance(config["components"], list):
        raise ConfigurationError("'components' must be a list")

    for i, component in enumerate(config["components"]):
        if not isinstance(component, dict):
            raise ConfigurationError(f"Component {i} must be a dictionary")

        required_component_fields = ["id", "type"]
        for field in required_component_fields:
            if field not in component:
                raise ConfigurationError(
                    f"Component {i} missing required field: '{field}'"
                )

    # Validate connections structure
    if not isinstance(config["connections"], list):
        raise ConfigurationError("'connections' must be a list")

    for i, connection in enumerate(config["connections"]):
        if not isinstance(connection, dict):
            raise ConfigurationError(f"Connection {i} must be a dictionary")

        required_connection_fields = ["id", "type", "source", "target"]
        for field in required_connection_fields:
            if field not in connection:
                raise ConfigurationError(
                    f"Connection {i} missing required field: '{field}'"
                )

    # Validate metadata structure if present
    if "metadata" in config:
        if not isinstance(config["metadata"], dict):
            raise ConfigurationError("'metadata' must be a dictionary")

    # Validate simulation structure if present
    if "simulation" in config:
        if not isinstance(config["simulation"], dict):
            raise ConfigurationError("'simulation' must be a dictionary")

    logger.info("Configuration structure validation passed")
    return True


def validate_component_references(config: Dict[str, Any]) -> bool:
    """
    Validate that all component references in connections are valid.

    Args:
        config: Configuration dictionary to validate

    Returns
    -------
        bool: True if valid, raises ConfigurationError if invalid

    Raises
    ------
        ConfigurationError: If component references are invalid
    """
    # Get all component IDs
    component_ids = {comp["id"] for comp in config["components"]}

    # Check all connections reference valid components
    for i, connection in enumerate(config["connections"]):
        source = connection.get("source")
        target = connection.get("target")

        if source not in component_ids:
            raise ConfigurationError(
                f"Connection {i} ({connection['id']}) references unknown source component: '{source}'"
            )

        if target not in component_ids:
            raise ConfigurationError(
                f"Connection {i} ({connection['id']}) references unknown target component: '{target}'"
            )

    logger.info("Component reference validation passed")
    return True


def get_default_simulation_params() -> Dict[str, Any]:
    """
    Get default simulation parameters.

    Returns
    -------
        Dict[str, Any]: Default simulation parameters
    """
    return {
        "mechanism": CANTERA_MECHANISM,
        "time_step": 0.001,
        "max_time": 10.0,
        "solver_type": "CVODE_BDF",
        "rtol": 1.0e-6,
        "atol": 1.0e-9,
    }


def normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize configuration by adding default values and converting units.

    Args:
        config: Raw configuration dictionary

    Returns
    -------
        Dict[str, Any]: Normalized configuration dictionary
    """
    normalized = config.copy()

    # Add default simulation parameters if not present
    if "simulation" not in normalized:
        normalized["simulation"] = get_default_simulation_params()
    else:
        # Merge with defaults
        default_sim = get_default_simulation_params()
        default_sim.update(normalized["simulation"])
        normalized["simulation"] = default_sim

    # Add default metadata if not present
    if "metadata" not in normalized:
        normalized["metadata"] = {
            "name": "Unnamed Configuration",
            "description": "No description provided",
            "version": "1.0",
        }

    # Normalize component properties
    for component in normalized["components"]:
        # Ensure all components have a properties dict
        if "properties" not in component:
            # Move all non-standard fields to properties
            properties = {}
            standard_fields = {"id", "type", "metadata", "properties"}
            for key, value in list(component.items()):
                if key not in standard_fields:
                    properties[key] = value
                    del component[key]
            component["properties"] = properties

    # Normalize connection properties
    for connection in normalized["connections"]:
        # Ensure all connections have a properties dict
        if "properties" not in connection:
            # Move all non-standard fields to properties
            properties = {}
            standard_fields = {
                "id",
                "type",
                "source",
                "target",
                "metadata",
                "properties",
            }
            for key, value in list(connection.items()):
                if key not in standard_fields:
                    properties[key] = value
                    del connection[key]
            connection["properties"] = properties

    logger.info("Configuration normalization completed")
    return normalized


def load_config_file(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from JSON or YAML file with validation.

    Args:
        config_path: Path to the configuration file

    Returns
    -------
        Dict[str, Any]: Validated and normalized configuration dictionary

    Raises
    ------
        FileNotFoundError: If the configuration file doesn't exist
        ConfigurationError: If the configuration is invalid
        ImportError: If PyYAML is required but not available
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    _, ext = os.path.splitext(config_path.lower())

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            if ext in [".yaml", ".yml"]:
                if not YAML_AVAILABLE:
                    raise ImportError(
                        "PyYAML is required to load YAML configuration files. "
                        "Install with: pip install PyYAML"
                    )
                config = yaml.safe_load(f)
            else:
                config = json.load(f)

        logger.info(f"Successfully loaded configuration from: {config_path}")

        # Validate configuration structure
        validate_config_structure(config)
        validate_component_references(config)

        # Normalize configuration
        normalized_config = normalize_config(config)

        return normalized_config

    except yaml.YAMLError as e:
        raise ConfigurationError(f"YAML parsing error in {config_path}: {e}")
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"JSON parsing error in {config_path}: {e}")
    except Exception as e:
        raise ConfigurationError(f"Error loading configuration from {config_path}: {e}")


def get_initial_config() -> Dict[str, Any]:
    """
    Load the initial configuration from the sample config file.

    Supports both JSON and YAML formats. Prefers YAML if available.

    Returns
    -------
        Dict[str, Any]: Initial configuration dictionary

    Raises
    ------
        FileNotFoundError: If no configuration file is found
        ConfigurationError: If the configuration is invalid
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data")

    # Try YAML first, then fallback to JSON
    yaml_path = os.path.join(data_dir, "sample_config.yaml")
    json_path = os.path.join(data_dir, "sample_config.json")

    if os.path.exists(yaml_path) and YAML_AVAILABLE:
        logger.info(f"Loading initial configuration from YAML: {yaml_path}")
        return load_config_file(yaml_path)
    elif os.path.exists(json_path):
        logger.info(f"Loading initial configuration from JSON: {json_path}")
        return load_config_file(json_path)
    else:
        raise FileNotFoundError(
            f"No configuration file found. Expected either {yaml_path} or {json_path}"
        )


def get_config_from_path(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from a specific path with validation.

    Args:
        config_path: Path to the configuration file

    Returns
    -------
        Dict[str, Any]: Validated and normalized configuration dictionary

    Raises
    ------
        FileNotFoundError: If the configuration file doesn't exist
        ConfigurationError: If the configuration is invalid
    """
    return load_config_file(config_path)


def save_config_to_file(
    config: Dict[str, Any], file_path: str, format_type: str = "yaml"
) -> None:
    """
    Save configuration to a file in the specified format.

    Args:
        config: Configuration dictionary to save
        file_path: Path where to save the configuration
        format_type: Format to save ('yaml' or 'json')

    Raises
    ------
        ConfigurationError: If there's an error saving the configuration
        ImportError: If PyYAML is required but not available for YAML format
    """
    try:
        # Validate configuration before saving
        validate_config_structure(config)
        validate_component_references(config)

        with open(file_path, "w", encoding="utf-8") as f:
            if format_type.lower() in ["yaml", "yml"]:
                if not YAML_AVAILABLE:
                    raise ImportError(
                        "PyYAML is required to save YAML configuration files. "
                        "Install with: pip install PyYAML"
                    )
                yaml.dump(
                    config, f, default_flow_style=False, indent=2, sort_keys=False
                )
            else:
                json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info(f"Configuration saved successfully to: {file_path}")

    except Exception as e:
        raise ConfigurationError(f"Error saving configuration to {file_path}: {e}")


def get_component_by_id(
    config: Dict[str, Any], component_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a component by its ID from the configuration.

    Args:
        config: Configuration dictionary
        component_id: ID of the component to find

    Returns
    -------
        Optional[Dict[str, Any]]: Component dictionary if found, None otherwise
    """
    for component in config.get("components", []):
        if component.get("id") == component_id:
            return component
    return None


def get_connections_for_component(
    config: Dict[str, Any], component_id: str
) -> List[Dict[str, Any]]:
    """
    Get all connections involving a specific component.

    Args:
        config: Configuration dictionary
        component_id: ID of the component

    Returns
    -------
        List[Dict[str, Any]]: List of connections involving the component
    """
    connections = []
    for connection in config.get("connections", []):
        if (
            connection.get("source") == component_id
            or connection.get("target") == component_id
        ):
            connections.append(connection)
    return connections
