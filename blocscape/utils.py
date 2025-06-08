"""Utility functions for the Boulder application."""


def config_to_cyto_elements(config):
    """Convert the JSON-like configuration to two lists of Cytoscape elements.

    Args:
        config: Configuration dictionary containing components and connections

    Returns:
        list: nodes + edges for Cytoscape
    """
    nodes = []
    edges = []

    # Add nodes
    for comp in config["components"]:
        node_data = {
            "id": comp["id"],
            "label": f"{comp['id']} ({comp['type']})",
            "type": comp["type"],
            "properties": comp["properties"],
        }
        # Add temperature to top-level data for Cytoscape mapping
        temp = comp["properties"].get("temperature")
        if temp is not None:
            try:
                node_data["temperature"] = float(temp)
            except Exception:
                node_data["temperature"] = temp
        nodes.append({"data": node_data})

    # Add edges
    for conn in config["connections"]:
        edges.append(
            {
                "data": {
                    "id": conn["id"],
                    "source": conn["source"],
                    "target": conn["target"],
                    "label": f"{conn['id']} ({conn['type']})",
                    "type": conn["type"],
                    "properties": conn["properties"],
                }
            }
        )

    return nodes + edges


def label_with_unit(key: str) -> str:
    """Add units to property labels for display."""
    unit_map = {
        "pressure": "pressure (Pa)",
        "composition": "composition (%mol)",
        "temperature": "temperature (K)",
        "mass_flow_rate": "mass flow rate (kg/s)",
    }
    return unit_map.get(key, key) 