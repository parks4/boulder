"""Tests for ``sankey_links_for_api`` and the ``sankey_link_colors`` plugin slot.

Asserts:
- Literal hex/rgb colors pass through unchanged to the API payload.
- ``mass`` / ``enthalpy`` / ``heat`` stay semantic for frontend theming.
- Species keys resolve to colors registered via the plugin slot.
- When no plugin registers colors, Boulder's light-theme fallback is used.
"""

from boulder.cantera_converter import BoulderPlugins
from boulder.sankey import _species_sankey_hex_colors, sankey_links_for_api


def test_sankey_links_for_api_passes_through_hex():
    """Assert ``#``/``rgb`` link colors are copied unchanged to the API payload."""
    links = {
        "source": [0],
        "target": [1],
        "value": [1.0],
        "color": ["#AABBCC", "rgb(1,2,3)"],
        "label": ["a", "b"],
    }
    out = sankey_links_for_api(links)
    assert out["color"] == ["#AABBCC", "rgb(1,2,3)"]
    assert links["color"] == ["#AABBCC", "rgb(1,2,3)"]


def test_sankey_links_for_api_keeps_flow_semantics():
    """Assert mass/enthalpy/heat semantic keys are not converted to hex."""
    links = {
        "source": [0, 0],
        "target": [1, 1],
        "value": [1.0, 2.0],
        "color": ["mass", "heat"],
        "label": ["", ""],
    }
    out = sankey_links_for_api(links)
    assert out["color"] == ["mass", "heat"]


def test_species_hex_colors_uses_plugin_slot_when_registered():
    """Assert _species_sankey_hex_colors reads from the plugin sankey_link_colors slot."""
    custom = {"H2": "#111111", "CH4": "#222222", "Cs": "#333333"}
    plugins = BoulderPlugins()
    plugins.sankey_link_colors = custom
    colors = _species_sankey_hex_colors(plugins=plugins)
    assert colors == custom


def test_species_hex_colors_fallback_when_no_plugin():
    """Assert _species_sankey_hex_colors returns Boulder light-theme defaults when no plugin slot."""
    from boulder.utils import get_sankey_theme_config

    plugins = BoulderPlugins()
    assert plugins.sankey_link_colors is None
    colors = _species_sankey_hex_colors(plugins=plugins)
    lc = get_sankey_theme_config("light")["link_colors"]
    assert colors == {"H2": lc["H2"], "CH4": lc["CH4"], "Cs": lc["Cs"]}


def test_sankey_links_for_api_species_use_registered_plugin_colors():
    """Assert sankey_links_for_api resolves H2/CH4/Cs via the plugin slot, not bloc directly."""
    custom = {"H2": "#aaaaaa", "CH4": "#bbbbbb", "Cs": "#cccccc"}
    plugins = BoulderPlugins()
    plugins.sankey_link_colors = custom

    links = {
        "source": [0, 0, 0],
        "target": [1, 1, 1],
        "value": [1.0, 1.0, 1.0],
        "color": ["H2", "CH4", "Cs"],
        "label": ["", "", ""],
    }
    out = sankey_links_for_api(links, plugins=plugins)
    assert out["color"] == ["#aaaaaa", "#bbbbbb", "#cccccc"]
