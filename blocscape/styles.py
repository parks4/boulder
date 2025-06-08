"""Cytoscape styling configuration for the reactor network graph."""

# Global variable to control temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Cytoscape stylesheet
CYTOSCAPE_STYLESHEET = [
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