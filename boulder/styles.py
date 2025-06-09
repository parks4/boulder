"""Cytoscape styling configuration for the reactor network graph."""

# Global variable to control temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Light theme cytoscape stylesheet
CYTOSCAPE_STYLESHEET_LIGHT = [
    {
        "selector": "node",
        "style": {
            "content": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "background-color": (
                "mapData(temperature, 300, 2273, deepskyblue, tomato)"
                if USE_TEMPERATURE_SCALE
                else "#BEE"
            ),
            "text-outline-color": "#555",
            "text-outline-width": 2,
            "color": "#fff",
            "width": "80px",
            "height": "80px",
            "text-wrap": "wrap",
            "text-max-width": "80px",
        },
    },
    {
        "selector": "[type = 'Reservoir']",
        "style": {
            "shape": "octagon",
        },
    },
    {
        "selector": "edge",
        "style": {
            "content": "data(label)",
            "text-rotation": "none",
            "text-margin-y": -10,
            "curve-style": "taxi",
            "taxi-direction": "rightward",
            "taxi-turn": 50,
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#555",
            "line-color": "#555",
            "text-wrap": "wrap",
            "text-max-width": "80px",
        },
    },
]

# Dark theme cytoscape stylesheet
CYTOSCAPE_STYLESHEET_DARK = [
    {
        "selector": "node",
        "style": {
            "content": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "background-color": (
                "mapData(temperature, 300, 2273, #4A90E2, #E94B3C)"
                if USE_TEMPERATURE_SCALE
                else "#4A90E2"
            ),
            "text-outline-color": "#222",
            "text-outline-width": 2,
            "color": "#fff",
            "width": "80px",
            "height": "80px",
            "text-wrap": "wrap",
            "text-max-width": "80px",
        },
    },
    {
        "selector": "[type = 'Reservoir']",
        "style": {
            "shape": "octagon",
        },
    },
    {
        "selector": "edge",
        "style": {
            "content": "data(label)",
            "text-rotation": "none",
            "text-margin-y": -10,
            "curve-style": "taxi",
            "taxi-direction": "rightward",
            "taxi-turn": 50,
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#ccc",
            "line-color": "#ccc",
            "text-wrap": "wrap",
            "text-max-width": "80px",
            "color": "#fff",
        },
    },
]

# Default stylesheet (light theme)
CYTOSCAPE_STYLESHEET = CYTOSCAPE_STYLESHEET_LIGHT


def get_cytoscape_stylesheet(theme: str = "light") -> list:
    """Get the appropriate Cytoscape stylesheet for the given theme."""
    if theme == "dark":
        return CYTOSCAPE_STYLESHEET_DARK
    return CYTOSCAPE_STYLESHEET_LIGHT
