"""Utility functions for the Boulder application."""

from typing import Any, Dict, List


def config_to_cyto_elements(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert configuration to Cytoscape elements."""
    elements = []

    # Add nodes (reactors)
    for component in config.get("components", []):
        properties = component.get("properties", {})
        node_data = {
            "id": component["id"],
            "label": component["id"],
            "type": component["type"],
            "properties": properties,
        }

        # Flatten commonly used properties for Cytoscape mapping
        # This allows Cytoscape selectors like "mapData(temperature, ...)" to work
        if "temperature" in properties:
            node_data["temperature"] = properties["temperature"]
        if "pressure" in properties:
            node_data["pressure"] = properties["pressure"]
        if "composition" in properties:
            node_data["composition"] = properties["composition"]
        if "volume" in properties:
            node_data["volume"] = properties["volume"]

        elements.append({"data": node_data})

    # Add edges (connections)
    for connection in config.get("connections", []):
        properties = connection.get("properties", {})
        edge_data = {
            "id": connection["id"],
            "source": connection["source"],
            "target": connection["target"],
            "label": connection["type"],
            "type": connection["type"],  # Add type field for consistency
            "properties": properties,
        }

        # Flatten commonly used properties for Cytoscape mapping
        if "mass_flow_rate" in properties:
            edge_data["mass_flow_rate"] = properties["mass_flow_rate"]
        if "valve_coeff" in properties:
            edge_data["valve_coeff"] = properties["valve_coeff"]

        elements.append({"data": edge_data})

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
    yaml_files: set[Path] = set()
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

    # Use a set to track filenames and avoid duplicates
    seen_filenames = set()

    for yaml_file in sorted(yaml_files):
        filename = yaml_file.name

        # Skip duplicates based on filename
        if filename in seen_filenames:
            continue

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
                    "type": connection["type"],  # Add type field for consistency
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
    yaml_files: set[Path] = set()
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

        # Mark this filename as seen
        seen_filenames.add(filename)

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
        "volume": "volume (m³)",
        "valve_coeff": "valve coefficient (-)",
    }
    return unit_map.get(key, key)


# Plot theme utilities
def get_plotly_theme_template(theme: str = "light") -> Dict[str, Any]:
    """Get Plotly theme template based on the current theme."""
    if theme == "dark":
        return {
            "layout": {
                "paper_bgcolor": "#1a1a1a",
                "plot_bgcolor": "#2d2d2d",
                "font": {"color": "#ffffff"},
                "title": {"font": {"color": "#ffffff"}},
                "xaxis": {
                    "gridcolor": "#404040",
                    "zerolinecolor": "#404040",
                    "tickcolor": "#ffffff",
                    "title": {"font": {"color": "#ffffff"}},
                    "tickfont": {"color": "#ffffff"},
                },
                "yaxis": {
                    "gridcolor": "#404040",
                    "zerolinecolor": "#404040",
                    "tickcolor": "#ffffff",
                    "title": {"font": {"color": "#ffffff"}},
                    "tickfont": {"color": "#ffffff"},
                },
                "legend": {
                    "font": {"color": "#ffffff"},
                    "bgcolor": "rgba(45, 45, 45, 0.8)",
                    "bordercolor": "#404040",
                },
                "colorway": [
                    "#4A90E2",  # Blue
                    "#7ED321",  # Green
                    "#F5A623",  # Orange
                    "#D0021B",  # Red
                    "#9013FE",  # Purple
                    "#50E3C2",  # Cyan
                    "#BD10E0",  # Magenta
                    "#B8E986",  # Light Green
                    "#FF6B6B",  # Light Red
                    "#4ECDC4",  # Teal
                ],
                "hovermode": "closest",
                "hoverlabel": {
                    "bgcolor": "#2d2d2d",
                    "font": {"color": "#ffffff"},
                    "bordercolor": "#404040",
                },
            }
        }
    else:  # light theme
        return {
            "layout": {
                "paper_bgcolor": "#ffffff",
                "plot_bgcolor": "#ffffff",
                "font": {"color": "#212529"},
                "title": {"font": {"color": "#212529"}},
                "xaxis": {
                    "gridcolor": "#dee2e6",
                    "zerolinecolor": "#dee2e6",
                    "tickcolor": "#212529",
                    "title": {"font": {"color": "#212529"}},
                    "tickfont": {"color": "#212529"},
                },
                "yaxis": {
                    "gridcolor": "#dee2e6",
                    "zerolinecolor": "#dee2e6",
                    "tickcolor": "#212529",
                    "title": {"font": {"color": "#212529"}},
                    "tickfont": {"color": "#212529"},
                },
                "legend": {
                    "font": {"color": "#212529"},
                    "bgcolor": "rgba(255, 255, 255, 0.8)",
                    "bordercolor": "#dee2e6",
                },
                "colorway": [
                    "#1f77b4",  # Blue
                    "#ff7f0e",  # Orange
                    "#2ca02c",  # Green
                    "#d62728",  # Red
                    "#9467bd",  # Purple
                    "#8c564b",  # Brown
                    "#e377c2",  # Pink
                    "#7f7f7f",  # Gray
                    "#bcbd22",  # Olive
                    "#17becf",  # Cyan
                ],
                "hovermode": "closest",
                "hoverlabel": {
                    "bgcolor": "#ffffff",
                    "font": {"color": "#212529"},
                    "bordercolor": "#dee2e6",
                },
            }
        }


def get_sankey_theme_config(theme: str = "light") -> Dict[str, Any]:
    """Get Sankey diagram theme configuration."""
    if theme == "dark":
        return {
            "paper_bgcolor": "#1a1a1a",
            "plot_bgcolor": "#2d2d2d",
            "font": {"color": "#ffffff", "size": 12},
            "title": {"font": {"color": "#ffffff"}},
            "node_colors": {
                "default": "#4A90E2",
                "reservoir": "#7ED321",
                "reactor": "#F5A623",
            },
            "link_colors": {
                "mass": "#B0B0B0",
                "enthalpy": "#4A90E2",
                "H2": "#B481FF",
                "CH4": "#6828B4",
                "heat": "#F5A623",
            },
        }
    else:  # light theme
        return {
            "paper_bgcolor": "#ffffff",
            "plot_bgcolor": "#ffffff",
            "font": {"color": "#212529", "size": 12},
            "title": {"font": {"color": "#212529"}},
            "node_colors": {
                "default": "#1f77b4",
                "reservoir": "#2ca02c",
                "reactor": "#ff7f0e",
            },
            "link_colors": {
                "mass": "pink",
                "enthalpy": "purple",
                "H2": "#B481FF",
                "CH4": "#6828B4",
                "heat": "green",
            },
        }


def apply_theme_to_figure(fig, theme: str = "light"):
    """Apply theme to a Plotly figure."""
    theme_config = get_plotly_theme_template(theme)
    fig.update_layout(**theme_config["layout"])
    return fig
