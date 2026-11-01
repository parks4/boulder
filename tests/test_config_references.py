"""Tests for the optional top-level ``references:`` STONE v2 section."""

import pytest
import yaml

from boulder.config import (
    convert_to_stone_format,
    merge_config_into_yaml,
    normalize_config,
    validate_config,
)
from boulder.runset import expand_scenarios

REFS = {
    "pid": {"doc_no": "EX-PID-001", "rev": "A", "sheet": 1, "title": "Example P&ID"}
}

_NET = [
    {"id": "feed", "Reservoir": {"temperature": 300, "composition": "N2:1"}},
    {"id": "reactor", "IdealGasReactor": {"volume": 1.0e-3}},
    {"id": "outlet", "Reservoir": {"temperature": 300, "composition": "N2:1"}},
    {
        "id": "mfc",
        "MassFlowController": {"mass_flow_rate": 0.001},
        "source": "feed",
        "target": "reactor",
    },
    {
        "id": "valve",
        "Valve": {"valve_coeff": 1.0},
        "source": "reactor",
        "target": "outlet",
    },
]


def _single(**extra):
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "settings": {"end_time": 1.0, "dt": 1.0},
        "network": _NET,
        **extra,
    }


def _staged(**extra):
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "settings": {"end_time": 1.0, "dt": 1.0},
        "stages": {
            "s1": {"mechanism": "gri30.yaml", "solver": "advance_to_steady_state"}
        },
        "s1": _NET,
        **extra,
    }


@pytest.mark.parametrize("make", [_single, _staged])
def test_references_survive_normalize_validate_and_export(make):
    """references: is accepted and kept by normalize, validate and STONE export."""
    normalized = normalize_config(make(references=REFS))
    assert normalized["references"] == REFS
    assert validate_config(normalized)["references"] == REFS
    assert convert_to_stone_format(normalized)["references"] == REFS


def test_references_survive_scenario_expansion():
    """Guard (also passes on main): an overlay keeps the base's references:."""
    base = _single(references=REFS, scenarios={"hot": {"settings": {"dt": 0.5}}})
    expanded = dict(expand_scenarios(base))
    assert expanded["hot"]["references"] == REFS


def test_references_survive_yaml_save_round_trip():
    """merge_config_into_yaml keeps references: in the saved YAML text."""
    text = yaml.safe_dump(_single(references=REFS), sort_keys=False)
    out, _ = merge_config_into_yaml(normalize_config(_single(references=REFS)), text)
    assert yaml.safe_load(out)["references"] == REFS


@pytest.mark.parametrize("make", [_single, _staged])
def test_references_must_be_a_mapping(make):
    """A non-mapping references: raises a clear error naming the key."""
    with pytest.raises(ValueError, match="'references:' must be a mapping"):
        normalize_config(make(references=["EX-PID-001"]))


@pytest.mark.parametrize("make", [_single, _staged])
def test_config_without_references_round_trips(make):
    """No references: -> validate -> export -> YAML -> reload works (exported null is accepted)."""
    validated = validate_config(normalize_config(make()))
    exported = yaml.safe_load(yaml.safe_dump(convert_to_stone_format(validated)))
    assert normalize_config(exported).get("references") is None
