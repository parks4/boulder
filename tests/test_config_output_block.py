import pytest

from boulder.config import convert_to_stone_format, normalize_config, validate_config


def test_output_block_is_preserved_through_validation_and_conversion():
    """Assert that output: block survives normalize + validate + convert_to_stone_format."""
    config = {
        "network": [
            {
                "id": "upstream",
                "Reservoir": {"temperature": 300, "composition": "N2:1"},
            },
            {
                "id": "reactor_id1",
                "IdealGasReactor": {"volume": 1.0e-3},
            },
            {
                "id": "mfc1",
                "MassFlowController": {"mass_flow_rate": 0.001},
                "source": "upstream",
                "target": "reactor_id1",
            },
        ],
        "settings": {"end_time": 1.0, "dt": 1.0},
        "output": {
            "reactor_id1": ["temperature, K", "pressure, bar"],
        },
    }

    normalized = normalize_config(config)
    validated = validate_config(normalized)
    assert "output" in validated and isinstance(validated["output"], dict)
    assert "reactor_id1" in validated["output"]

    roundtrip = convert_to_stone_format(validated)
    assert "network" in roundtrip
    assert "output" in roundtrip and roundtrip["output"] == config["output"]


def test_convert_to_stone_format_staged_solver_block():
    """Assert multi-stage export writes ``stages:`` with ``solver:`` from normalized groups.

    Groups use the normalized ``solver`` dict (not legacy ``solve``).

    Regression: convert_to_stone_format used g["solve"] which raised KeyError 'solve'
    for configs normalized from STONE files that use ``solver:`` blocks.
    """
    internal = {
        "nodes": [
            {
                "id": "inlet",
                "type": "Reservoir",
                "group": "s1",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
        ],
        "connections": [],
        "groups": {
            "s1": {
                "stage_order": 1,
                "mechanism": "gri30.yaml",
                "solver": {"kind": "advance_to_steady_state", "mode": "steady"},
            },
        },
    }
    stone = convert_to_stone_format(internal)
    assert "stages" in stone
    assert stone["stages"]["s1"]["solver"]["kind"] == "advance_to_steady_state"
    assert "solve" not in stone["stages"]["s1"]


def test_convert_to_stone_format_staged_legacy_solve():
    """Assert export still works when groups carry the legacy ``solve`` key (no ``solver`` block).

    Legacy in-memory configs that were never re-normalized still have a bare ``solve``
    string on the group. Export must produce ``stages: {s1: {solve: ...}}`` without error.
    """
    internal = {
        "nodes": [
            {
                "id": "inlet",
                "type": "Reservoir",
                "group": "s1",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
        ],
        "connections": [],
        "groups": {
            "s1": {
                "stage_order": 1,
                "mechanism": "gri30.yaml",
                "solve": "advance_to_steady_state",
            },
        },
    }
    stone = convert_to_stone_format(internal)
    assert stone["stages"]["s1"]["solve"] == "advance_to_steady_state"
    assert "solver" not in stone["stages"]["s1"]


def test_convert_to_stone_format_staged_missing_solver_raises():
    """Assert export raises ValueError when a group has neither ``solver`` nor ``solve``.

    Guards against silent bad output when group metadata is malformed.
    """
    internal = {
        "nodes": [
            {"id": "inlet", "type": "Reservoir", "group": "s1",
             "properties": {"temperature": 300.0}},
        ],
        "connections": [],
        "groups": {
            "s1": {"stage_order": 1, "mechanism": "gri30.yaml"},
        },
    }
    with pytest.raises(ValueError, match="solver"):
        convert_to_stone_format(internal)
