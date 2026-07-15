"""A node-level ``plot_options:`` property (species show/hide hints) survives normalization.

Lets an example author hide dominant/uninteresting species (e.g. N2, O2) and
force minor-but-relevant ones (reaction intermediates that never crack the
frontend's top-12-by-magnitude heuristic) into the Mole/Mass fraction charts
by default. The frontend still lets the user re-click a hidden trace's legend
entry to reveal it -- this only sets the *initial* visibility.
"""

from __future__ import annotations

from boulder.config import load_yaml_string_with_comments, normalize_config

_YAML = """
phases:
  gas:
    mechanism: gri30.yaml
network:
- id: reactor
  IdealGasReactor:
    volume: 1e-3
    initial:
      temperature: 900.0
      pressure: 101325.0
      composition: CH4:1,O2:2,N2:7.52
  plot_options:
    hide_species: [N2, O2]
    show_species: [CH3, OH]
"""


def test_node_plot_property_survives_normalization() -> None:
    """A node's ``plot_options:`` block ends up in properties.plot_options after normalization."""
    normalized = normalize_config(load_yaml_string_with_comments(_YAML))
    (node,) = [n for n in normalized["nodes"] if n["id"] == "reactor"]

    plot_cfg = node["properties"].get("plot_options")
    assert plot_cfg is not None
    assert plot_cfg["hide_species"] == ["N2", "O2"]
    assert plot_cfg["show_species"] == ["CH3", "OH"]

    # The reactor kind's own properties must be unaffected by the extra key.
    assert node["properties"]["volume"] == 1e-3


def test_node_without_plot_property_has_no_plot_key() -> None:
    """A node with no ``plot_options:`` block simply has no key -- no default noise."""
    yaml_str = _YAML.replace(
        "  plot_options:\n    hide_species: [N2, O2]\n    show_species: [CH3, OH]\n", ""
    )
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))
    (node,) = [n for n in normalized["nodes"] if n["id"] == "reactor"]
    assert "plot_options" not in node["properties"]
