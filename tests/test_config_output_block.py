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


def test_convert_to_stone_format_staged_emits_solver_scalar():
    """Assert multi-stage export writes ``solver: <kind>`` as a scalar string in ``stages:``.

    Normalized groups have ``solver: {kind: ..., mode: ...}``. Export must emit the
    compact scalar form ``solver: advance_to_steady_state`` (not a nested block).
    Regression: previously raised KeyError 'solve'; now must not emit ``kind:`` at all.
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
    assert stone["stages"]["s1"]["solver"] == "advance_to_steady_state"
    assert "solve" not in stone["stages"]["s1"]
    assert "kind" not in stone["stages"]["s1"]


def test_convert_to_stone_format_staged_advance_emits_advance_time_sibling():
    """Assert ``advance`` kind exports ``solver: advance`` + ``advance_time:`` as siblings.

    advance_time must appear at the same level as ``solver:``, not nested inside it.
    """
    internal = {
        "nodes": [
            {
                "id": "inlet",
                "type": "Reservoir",
                "group": "s1",
                "properties": {"temperature": 300.0},
            },
        ],
        "connections": [],
        "groups": {
            "s1": {
                "stage_order": 1,
                "mechanism": "gri30.yaml",
                "solver": {
                    "kind": "advance",
                    "advance_time": 1e-3,
                    "mode": "transient",
                },
            },
        },
    }
    stone = convert_to_stone_format(internal)
    stage = stone["stages"]["s1"]
    assert stage["solver"] == "advance"
    assert stage["advance_time"] == 1e-3
    assert "kind" not in stage


def test_convert_to_stone_format_staged_missing_solver_raises():
    """Assert export raises ValueError when a group has neither ``solver`` nor ``solve``.

    Guards against silent bad output when group metadata is malformed.
    """
    internal = {
        "nodes": [
            {
                "id": "inlet",
                "type": "Reservoir",
                "group": "s1",
                "properties": {"temperature": 300.0},
            },
        ],
        "connections": [],
        "groups": {
            "s1": {"stage_order": 1, "mechanism": "gri30.yaml"},
        },
    }
    with pytest.raises(ValueError, match="solver"):
        convert_to_stone_format(internal)
