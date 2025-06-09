"""Utility functions for the Boulder application."""

from typing import Any, Dict, List


def config_to_cyto_elements(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert configuration to Cytoscape elements."""
    elements = []

    # Add nodes (reactors)
    for component in config.get("components", []):
        elements.append(
            {
                "data": {
                    "id": component["id"],
                    "label": component["id"],
                    "type": component["type"],
                    "properties": component.get("properties", {}),
                }
            }
        )

    # Add edges (connections)
    for connection in config.get("connections", []):
        elements.append(
            {
                "data": {
                    "id": connection["id"],
                    "source": connection["source"],
                    "target": connection["target"],
                    "label": connection["type"],
                    "properties": connection.get("properties", {}),
                }
            }
        )

    return elements


def get_available_cantera_mechanisms() -> List[Dict[str, str]]:
    """Get all available Cantera mechanism files from data directories.

    Returns
    -------
        List of dictionaries with 'label' and 'value' keys for dropdown options.
    """
    from pathlib import Path

    import cantera as ct

    mechanisms = []

    # Get Cantera data directories
    try:
        data_dirs = ct.get_data_directories()
    except AttributeError:
        # Fallback for older Cantera versions
        cantera_dir = Path(ct.__file__).parent
        data_dirs = [str(cantera_dir / "data")]

    # Scan for YAML mechanism files
    yaml_files = set()
    for data_dir in data_dirs:
        data_path = Path(data_dir)
        if data_path.exists():
            # Look for .yaml and .yml files
            for ext in ["*.yaml", "*.yml"]:
                yaml_files.update(data_path.glob(ext))

    # Convert to dropdown options, excluding some internal/test files
    exclude_patterns = [
        "test",
        "example",
        "tutorial",
        "sample",
        "demo",
        "validation",
        "transport",
        "pre-commit",
        "config",
        "template",
        "species",
        "thermo",
    ]

    for yaml_file in sorted(yaml_files):
        filename = yaml_file.name
        # Skip files that match exclude patterns or don't seem like mechanism files
        if any(pattern in filename.lower() for pattern in exclude_patterns):
            continue

        # Skip files that are clearly not mechanism files (dot files, etc)
        if filename.startswith(".") or len(filename) < 5:
            continue

        # Create a readable label
        label = filename.replace(".yaml", "").replace(".yml", "").replace("_", " ")
        label = " ".join(word.capitalize() for word in label.split())

        # Add special descriptions for known mechanisms
        if filename == "gri30.yaml":
            label = "GRI 3.0 (Natural Gas Combustion)"
        elif filename == "h2o2.yaml":
            label = "H2/O2 (Hydrogen Combustion)"
        elif filename == "air.yaml":
            label = "Air (Ideal Gas Properties)"
        elif "methane" in filename.lower():
            label += " (Methane)"
        elif "hydrogen" in filename.lower():
            label += " (Hydrogen)"
        elif "ethane" in filename.lower():
            label += " (Ethane)"

        mechanisms.append({"label": label, "value": filename})

    return mechanisms


def label_with_unit(key: str) -> str:
    """Add units to property labels for display."""
    unit_map = {
        "pressure": "pressure (Pa)",
        "composition": "composition (%mol)",
        "temperature": "temperature (K)",
        "mass_flow_rate": "mass flow rate (kg/s)",
    }
    return unit_map.get(key, key)
