"""Configuration management for the Boulder application.

Supports YAML format with 🪨 STONE standard - an elegant configuration format
where component types are keys containing their properties.
"""

import os
from typing import Any, Dict, Optional, Tuple

import yaml
from ruamel.yaml import YAML

# Global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Global variable to control which converter to use
# Unified converter architecture - no longer needed
# USE_DUAL_CONVERTER = True

# Global variable for the Cantera mechanism to use consistently across the application
CANTERA_MECHANISM = "gri30.yaml"

# Theme setting: "light", "dark", or "system"
THEME = "system"


def get_yaml_with_comments():
    """Get a ruamel.yaml YAML object configured to preserve comments."""
    yaml_obj = YAML()
    yaml_obj.preserve_quotes = True
    yaml_obj.width = 4096  # Prevent line wrapping
    # Configure indentation to match pretty-format-yaml expectations
    # mapping=2: 2 spaces for dictionary keys
    # sequence=2: 2 spaces for list items after the dash
    # offset=0: no extra indentation for the dash itself
    yaml_obj.indent(mapping=2, sequence=2, offset=0)
    return yaml_obj


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


def load_config_file_with_comments(config_path: str):
    """Load configuration from YAML file preserving comments with 🪨 STONE standard."""
    _, ext = os.path.splitext(config_path.lower())

    if ext not in [".yaml", ".yml"]:
        raise ValueError(
            f"Only YAML format with 🪨 STONE standard (.yaml/.yml) files are supported. "
            f"Got: {ext}"
        )

    yaml_obj = get_yaml_with_comments()
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml_obj.load(f)


def normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize configuration from YAML with 🪨 STONE standard to internal format.

    The 🪨 STONE standard format:
    - nodes: list of components (reactors, reservoirs, etc.)
    - connections: list of connections between nodes
    - phases: chemistry/phase configuration (e.g., gas mechanisms)
    - settings: simulation-level settings
    - metadata: optional configuration metadata

    Converted to the internal format used by converters:
    - nodes: list with { id, type, properties }
    - connections: list with { id, type, properties, source, target }
    - phases: chemistry/phase configuration (preserved)
    - settings: simulation-level settings (preserved)

    Example
    -------

        🪨 STONE format::

        nodes:
          - id: reactor1
            IdealGasReactor:
                temperature: 1000

    Internal format::

        nodes:
          - id: reactor1
            type: IdealGasReactor
            properties:
                temperature: 1000
    """
    normalized = config.copy()

    # Require new STONE schema keys
    if isinstance(normalized, dict):
        if "nodes" not in normalized:
            raise ValueError(
                "STONE format required: top-level 'nodes' missing. "
                "Please update your YAML configuration to use the new STONE schema with 'nodes', "
                "'phases', and 'settings'."
            )
        # Keep phases and settings as separate top-level sections (STONE standard)

    # Normalize nodes
    if "nodes" in normalized:
        for node in normalized["nodes"]:
            if "type" not in node:
                # Find the type key (anything that's not id, metadata, etc.)
                standard_fields = {"id", "metadata", "mechanism"}
                type_keys = [k for k in node.keys() if k not in standard_fields]

                if type_keys:
                    type_name = type_keys[0]  # Use the first type key found
                    properties = node[type_name]

                    # Remove the type key and add type + properties
                    del node[type_name]
                    node["type"] = type_name
                    node["properties"] = (
                        properties if isinstance(properties, dict) else {}
                    )
            # If a node-level mechanism is present, move it into properties for internal use
            if "mechanism" in node:
                props = node.setdefault("properties", {})
                if "mechanism" not in props:
                    props["mechanism"] = node["mechanism"]

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


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a normalized config using Pydantic schema and return a plain dict.

    This performs structural validation and cross-references (IDs, source/target) without
    building any network.
    """
    # Import locally to avoid import costs when not needed
    from .validation import validate_normalized_config

    model = validate_normalized_config(config)
    return model.dict()


def get_initial_config() -> Dict[str, Any]:
    """Load the initial configuration in YAML format with 🪨 STONE standard.

    Loads from configs/default.yaml using the elegant 🪨 STONE standard.
    """
    # Load from configs directory (YAML with 🪨 STONE standard)
    configs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs")
    stone_config_path = os.path.join(configs_dir, "default.yaml")

    if os.path.exists(stone_config_path):
        config = load_config_file(stone_config_path)
        normalized = normalize_config(config)
        return validate_config(normalized)
    else:
        raise FileNotFoundError(
            f"YAML configuration file with 🪨 STONE standard not found: {stone_config_path}"
        )


def get_initial_config_with_comments() -> tuple[Dict[str, Any], str]:
    """Load the initial configuration with comments preserved.

    Returns
    -------
        tuple: (normalized_config, original_yaml_string)
    """
    # Load from configs directory (YAML with 🪨 STONE standard)
    configs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs")
    stone_config_path = os.path.join(configs_dir, "default.yaml")

    if os.path.exists(stone_config_path):
        # Load with comments preserved
        config_with_comments = load_config_file_with_comments(
            stone_config_path
        )  # load YAML
        # Also read the raw file content to preserve original formatting
        with open(stone_config_path, "r", encoding="utf-8") as f:
            original_yaml = f.read()

        normalized_config = normalize_config(
            config_with_comments
        )  # convert to STONE format
        validated = validate_config(normalized_config)  # validate inputs
        return validated, original_yaml

    else:
        raise FileNotFoundError(
            f"YAML configuration file with 🪨 STONE standard not found: {stone_config_path}"
        )


def get_config_from_path(config_path: str) -> Dict[str, Any]:
    """Load configuration from a specific path."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = load_config_file(config_path)  # load YAML
    normalized = normalize_config(config)  # convert to STONE format
    return validate_config(normalized)  # validate inputs


def get_config_from_path_with_comments(config_path: str) -> tuple[Dict[str, Any], str]:
    """Load configuration from a specific path with comments preserved.

    Returns
    -------
    tuple
        (normalized_config, original_yaml_string)
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config_with_comments = load_config_file_with_comments(config_path)  # load YAML
    with open(config_path, "r", encoding="utf-8") as f:
        original_yaml = f.read()
    normalized = normalize_config(
        config_with_comments
    )  # convert to STONE format with comments
    return validate_config(normalized), original_yaml  # validate inputs


def convert_to_stone_format(config: dict) -> dict:
    """Convert internal format back to new STONE schema for file saving."""
    stone_config = {}

    # Copy metadata section as-is
    if "metadata" in config:
        stone_config["metadata"] = config["metadata"]

    # Copy phases and settings sections directly (STONE standard)
    if "phases" in config:
        stone_config["phases"] = config["phases"]

    if "settings" in config:
        stone_config["settings"] = config["settings"]

    # Convert nodes to STONE format
    if "nodes" in config:
        stone_config["nodes"] = []
        for node in config["nodes"]:
            # Build node with id first, then type as key containing properties
            node_type = node.get("type", "IdealGasReactor")
            props = dict(node.get("properties", {}) or {})
            mech_override = props.pop("mechanism", None)
            stone_node = {"id": node["id"], node_type: props}
            if mech_override is not None:
                stone_node["mechanism"] = mech_override
            stone_config["nodes"].append(stone_node)

    # Convert connections (same structure in new format)
    if "connections" in config:
        stone_config["connections"] = []
        for connection in config["connections"]:
            # Build connection with id first, then type as key, then source/target
            connection_type = connection.get("type", "MassFlowController")
            stone_connection = {
                "id": connection["id"],
                connection_type: connection.get("properties", {}),
                "source": connection["source"],
                "target": connection["target"],
            }
            stone_config["connections"].append(stone_connection)

    # Carry-through `output` section (STONE standard extension)
    if "output" in config:
        stone_config["output"] = config["output"]

    return stone_config


def yaml_to_string_with_comments(data) -> str:
    """Convert data to YAML string while preserving comments."""
    from io import StringIO

    yaml_obj = get_yaml_with_comments()
    stream = StringIO()
    yaml_obj.dump(data, stream)
    return stream.getvalue()


def load_yaml_string_with_comments(yaml_str: str):
    """Load YAML string while preserving comments."""
    from io import StringIO

    yaml_obj = get_yaml_with_comments()
    stream = StringIO(yaml_str)
    return yaml_obj.load(stream)


def save_config_to_file_with_comments(
    config: dict, file_path: str, original_yaml_str: Optional[str] = None
):
    """Save configuration to file, preserving comments when possible."""
    stone_config = convert_to_stone_format(config)

    if original_yaml_str:
        # Try to preserve the original structure and comments
        try:
            # Load the original YAML with comments
            original_data = load_yaml_string_with_comments(original_yaml_str)

            # Update the original data with new values while preserving structure
            updated_data = _update_yaml_preserving_comments(original_data, stone_config)

            # Save with comments preserved
            yaml_obj = get_yaml_with_comments()
            with open(file_path, "w", encoding="utf-8") as f:
                yaml_obj.dump(updated_data, f)
            return
        except Exception as e:
            print(f"Warning: Could not preserve comments, using standard format: {e}")

    # Fallback: save without comment preservation
    yaml_str = yaml_to_string_with_comments(stone_config)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)


def _update_yaml_preserving_comments(original_data, new_data):
    """Update YAML data while preserving comments and structure.

    This function recursively updates the original YAML structure with new values
    while preserving all comments and formatting.
    """
    # Import here to avoid circular imports
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if not isinstance(original_data, dict) or not isinstance(new_data, dict):
        return new_data

    # Create a copy that preserves comments and structure
    if isinstance(original_data, CommentedMap):
        updated = CommentedMap()
        # Copy original data to preserve comments
        for key, value in original_data.items():
            updated[key] = value
    else:
        updated = (
            original_data.copy()
            if hasattr(original_data, "copy")
            else dict(original_data)
        )

    # Update with new values
    for key, new_value in new_data.items():
        if key in updated:
            original_value = updated[key]

            # Handle dictionaries recursively
            if isinstance(original_value, dict) and isinstance(new_value, dict):
                updated[key] = _update_yaml_preserving_comments(
                    original_value, new_value
                )

            # Handle arrays/lists - this is the key fix
            elif isinstance(original_value, (list, CommentedSeq)) and isinstance(
                new_value, list
            ):
                updated[key] = _update_yaml_array_preserving_comments(
                    original_value, new_value
                )

            # For scalar values, just update
            else:
                updated[key] = new_value
        else:
            # New key, add it
            updated[key] = new_value

    return updated


def _update_yaml_array_preserving_comments(original_array, new_array):
    """Update an array while preserving comments on array items.

    This function matches items in the arrays by their 'id' field and preserves
    comments on each item while updating their values.
    """
    from ruamel.yaml.comments import CommentedSeq

    # Create a new commented sequence to preserve array comments
    if isinstance(original_array, CommentedSeq):
        updated_array = CommentedSeq()
        # Copy array-level comments by copying the entire original array first
        # then updating its contents
        for item in original_array:
            updated_array.append(item)

        # Now clear and rebuild with updated items
        updated_array.clear()
    else:
        updated_array = []

    # Create a mapping of original items by their ID for easy lookup
    original_by_id = {}
    for item in original_array:
        if isinstance(item, dict) and "id" in item:
            original_by_id[item["id"]] = item

    # Process each new item
    for new_item in new_array:
        if isinstance(new_item, dict) and "id" in new_item:
            item_id = new_item["id"]

            # If we have an original item with the same ID, merge it
            if item_id in original_by_id:
                original_item = original_by_id[item_id]
                updated_item = _update_yaml_item_preserving_comments(
                    original_item, new_item
                )
                updated_array.append(updated_item)
            else:
                # New item, add as-is
                updated_array.append(new_item)
        else:
            # Item without ID, add as-is
            updated_array.append(new_item)

    return updated_array


def _update_yaml_item_preserving_comments(original_item, new_item):
    """Update a single YAML item while preserving its STONE format structure.

    This function handles the specific case of nodes and connections
    which have a special structure in STONE format.
    """
    from ruamel.yaml.comments import CommentedMap

    if not isinstance(original_item, dict) or not isinstance(new_item, dict):
        return new_item

    # Create a copy that preserves comments and structure
    if isinstance(original_item, CommentedMap):
        updated_item = CommentedMap()
        # Copy original data to preserve comments
        for key, value in original_item.items():
            updated_item[key] = value
    else:
        updated_item = original_item.copy()

    # For STONE format, we need to preserve the structure but update values
    # The new_item comes in STONE format, so we can directly update
    for key, new_value in new_item.items():
        if key == "id":
            # Always update the ID
            updated_item[key] = new_value
        elif key in ["source", "target"]:
            # For connections, update source/target
            updated_item[key] = new_value
        elif key in updated_item:
            # For other keys that exist in original (like component type keys)
            if isinstance(updated_item[key], dict) and isinstance(new_value, dict):
                # Recursively update nested dictionaries
                updated_item[key] = _update_yaml_preserving_comments(
                    updated_item[key], new_value
                )
            else:
                updated_item[key] = new_value

    return updated_item


def load_config_file_with_py_support(
    config_path: str, verbose: bool = False
) -> Tuple[Dict[str, Any], str]:
    """Load configuration file with automatic Python to YAML conversion support.

    Logic:
    1. If .py file: convert to .yaml first, then load the .yaml
    2. If .yaml/.yml file: load directly
    3. Always return loaded config from a YAML file

    Args:
        config_path: Path to configuration file (.yaml, .yml, or .py)
        verbose: Enable verbose output

    Returns
    -------
        Tuple of (config_dict, yaml_file_path)

    Raises
    ------
        ValueError: If file type is not supported
        FileNotFoundError: If file doesn't exist
        RuntimeError: If conversion fails
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    _, ext = os.path.splitext(config_path.lower())

    # Step 0: Convert Python to YAML if needed (preliminary conversion step)
    yaml_path = config_path

    if ext == ".py":
        from .parser import convert_py_to_yaml

        if verbose:
            print(f"[Boulder] Detected Python file: {config_path}")
            print("[Boulder] Converting to YAML using sim2stone...")

        yaml_path = convert_py_to_yaml(config_path, verbose=verbose)

    elif ext not in [".yaml", ".yml"]:
        raise ValueError(
            f"Unsupported file format. Supported formats: .py, .yaml, .yml. Got: {ext}"
        )

    # Step 1 & 2: Common YAML processing pipeline (for both original YAML and converted Python)
    if verbose:
        print(f"[Boulder] Loading YAML file: {yaml_path}")

    config = load_config_file(yaml_path)
    return config, yaml_path


def load_config_file_with_py_support_and_comments(
    config_path: str, verbose: bool = False
) -> Tuple[Dict[str, Any], str, str]:
    """Load configuration file with Python support, preserving comments.

    Logic:
    1. If .py file: convert to .yaml first
    2. Always load from the resulting .yaml file with comments preserved

    Args:
        config_path: Path to configuration file (.yaml, .yml, or .py)
        verbose: Enable verbose output

    Returns
    -------
        Tuple of (config_dict, original_yaml_string, yaml_file_path)
    """
    # Step 1: Handle conversion if needed, get the YAML path
    config, yaml_path = load_config_file_with_py_support(config_path, verbose)

    # Step 2: Always read the YAML file with comments preserved
    with open(yaml_path, "r", encoding="utf-8") as f:
        original_yaml = f.read()

    return config, original_yaml, yaml_path
