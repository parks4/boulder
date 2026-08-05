"""A propagated process pressure is marked derived, so the GUI can hide it.

`propagate_terminal_pressure_defaults` materialises the component's pressure
onto every pressure-bearing node because the solver needs it there. That makes
it indistinguishable from an authored value in the Properties panel, where it
reads as a pin the user set and invites an edit that would either be re-derived
on the next normalise or create the very conflict the pass raises for.
"""

from __future__ import annotations

from typing import Any, Dict

from boulder.config import DERIVED_PROPERTIES_KEY, normalize_config


def _cfg() -> Dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "feed",
                "type": "Reservoir",
                "properties": {"temperature": 300, "composition": "CH4:1"},
            },
            {"id": "down", "type": "OutletSink", "properties": {"pressure": 130000.0}},
        ],
        "connections": [
            {
                "id": "c",
                "type": "MassFlowController",
                "source": "feed",
                "target": "down",
                "properties": {},
            }
        ],
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
    }


def _node(config: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    return next(n for n in config["nodes"] if n["id"] == node_id)


def test_a_propagated_pressure_records_the_node_it_came_from() -> None:
    normalized = normalize_config(_cfg())
    feed = _node(normalized, "feed")

    # Still materialised -- the solver reads it off the node.
    assert feed["properties"]["pressure"] == 130000.0
    # ...and marked, so the panel knows not to offer it as an input.
    assert feed["metadata"][DERIVED_PROPERTIES_KEY] == {"pressure": "down"}


def test_the_node_that_declared_the_pressure_is_not_marked() -> None:
    """Only filled-in values are derived; an authored one stays an input."""
    normalized = normalize_config(_cfg())
    down = _node(normalized, "down")

    assert down["properties"]["pressure"] == 130000.0
    assert (down.get("metadata") or {}).get(DERIVED_PROPERTIES_KEY) is None


def test_an_explicitly_declared_matching_pressure_is_not_marked() -> None:
    """The pass leaves it alone, so it is the author's value, not a derived one."""
    config = _cfg()
    _node(config, "feed")["properties"]["pressure"] = 130000.0

    normalized = normalize_config(config)
    feed = _node(normalized, "feed")

    assert feed["properties"]["pressure"] == 130000.0
    assert (feed.get("metadata") or {}).get(DERIVED_PROPERTIES_KEY) is None
