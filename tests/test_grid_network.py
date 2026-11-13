"""A generated cyclic grid network loads, solves and keeps its node positions.

The network (``grid_network.py``) has recirculation loops and pairs of equal
and opposite mass flow controllers between neighbours, like a compartment
network derived from a flow field.
"""

from __future__ import annotations

import copy

from grid_network import grid_network

from boulder.config import migrate_stone_config, normalize_config, validate_config
from boulder.sweep_runner import run_set


def test_layout_position_survives_normalize_and_validate():
    """Every node keeps ``metadata.layout_position`` through normalize + validate."""
    raw = grid_network(3, 2)
    cfg = copy.deepcopy(raw)
    migrate_stone_config(cfg)
    validated = validate_config(normalize_config(cfg))

    positions = {n["id"]: n["metadata"]["layout_position"] for n in validated["nodes"]}
    assert positions["r_2_1"] == {"x": 320, "y": 160}
    assert len(positions) == 3 * 2 + 2  # reactors + feed + exhaust


def test_cyclic_grid_solves_with_sankey_and_positions():
    """The Sankey links every flow-device pair and updated_nodes keep the positions."""
    raw = grid_network(3, 2)
    (outcome,) = run_set(raw, None, keep_payload=True, log=lambda _line: None)
    gui = outcome.gui

    names = gui["sankey_nodes"]
    linked = {
        (names[s], names[t])
        for s, t in zip(*(gui["sankey_links"][k] for k in ("source", "target")))
    }
    flows = {
        (c["source"], c["target"]) for c in raw["network"] if "MassFlowController" in c
    }
    assert linked == flows
    by_id = {n["id"]: n for n in gui["updated_nodes"]}
    assert by_id["r_1_0"]["metadata"]["layout_position"] == {"x": 160, "y": 0}
