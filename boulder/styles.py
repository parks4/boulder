"""Cytoscape styling configuration for the reactor network graph."""

# Global variable to control temperature scale coloring
# Single source of truth; avoid duplicating in other modules
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
        # Style for compound group nodes
        "selector": "node[isGroup]",
        "style": {
            "shape": "round-rectangle",
            "background-opacity": 0.05,
            "background-color": "#999",
            "border-width": 2,
            "border-color": "#999",
            "text-valign": "top",
            "text-halign": "center",
            "padding": "20px",
            "width": "label",
            "height": "label",
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
            # Ensure we can control draw order of edges
            "z-index-compare": "manual",
            # Keep default edges below walls
            "z-index": 5,
            # Slightly wider so they remain visible under walls
            "width": 6,
            "text-wrap": "wrap",
            "text-max-width": "80px",
        },
    },
    {
        # Emphasize Walls with a distinct color visible in light mode
        "selector": "edge[type = 'Wall']",
        "style": {
            "line-color": "#D0021B",
            "target-arrow-color": "#D0021B",
            # Draw walls on top
            "z-index": 20,
            # Slightly narrower so default edges peek around them
            "width": 4,
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
        # Style for compound group nodes
        "selector": "node[isGroup]",
        "style": {
            "shape": "round-rectangle",
            "background-opacity": 0.05,
            "background-color": "#ccc",
            "border-width": 2,
            "border-color": "#ccc",
            "text-valign": "top",
            "text-halign": "center",
            "padding": "20px",
            "width": "label",
            "height": "label",
            "color": "#fff",
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
            # Ensure we can control draw order of edges
            "z-index-compare": "manual",
            # Keep default edges below walls
            "z-index": 5,
            "text-wrap": "wrap",
            "text-max-width": "80px",
            "color": "#fff",
            # Slightly wider so they remain visible under walls
            "width": 6,
        },
    },
    {
        # Emphasize Walls with a distinct color visible in dark mode
        "selector": "edge[type = 'Wall']",
        "style": {
            "line-color": "#FF4D4D",
            "target-arrow-color": "#FF4D4D",
            # Draw walls on top
            "z-index": 20,
            # Slightly narrower so default edges peek around them
            "width": 3,
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
