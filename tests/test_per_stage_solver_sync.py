"""Tests for per-stage solver edits round-tripping through YAML sync.

Asserts that editing one stage's solver and syncing writes into its own
``stages: <id>: solver:`` YAML block, without touching other stages' solver
settings or clobbering fields the edit didn't touch. Guards against the bug
where ``convert_to_stone_format`` collapsed a stage's resolved solver dict
down to a bare ``kind`` string, silently dropping mode/rtol/atol/max_steps/
grid on every GUI-driven sync.
"""

from __future__ import annotations

import yaml

from boulder.config import (
    load_yaml_string_with_comments,
    merge_config_into_yaml,
    normalize_config,
)

_TWO_STAGE_YAML = """
metadata:
  title: two-stage solver sync test
phases:
  gas:
    mechanism: gri30.yaml
stages:
  psr_stage:
    mechanism: gri30.yaml
    solver:
      kind: advance_to_steady_state
      rtol: 1.0e-9
  pfr_stage:
    mechanism: gri30.yaml
    solver:
      kind: advance_to_steady_state
psr_stage:
- id: r1
  IdealGasReactor:
    volume: 1 L
pfr_stage:
- id: r2
  IdealGasReactor:
    volume: 1 L
"""


def _parse(yaml_str: str):
    return yaml.safe_load(yaml_str)


def _parse_output(yaml_str: str):
    """Parse a *merged* YAML string with the app's own ruamel-based loader.

    Needed because ruamel emits scientific-notation floats without a decimal
    point (``1e-10``), which PyYAML's ``safe_load`` — fine for constructing
    test fixtures, but stricter about float grammar — reads back as a plain
    string instead of a float.
    """
    return load_yaml_string_with_comments(yaml_str)


def test_editing_one_stage_solver_persists_only_that_stage():
    """Changing psr_stage's kind/mode/rtol syncs into its own block only."""
    config = normalize_config(_parse(_TWO_STAGE_YAML))

    # Simulate the GUI editing psr_stage's own solver (StageCard writing into
    # config.groups[stageId].solver), switching it to transient with a
    # custom tolerance.
    config["groups"]["psr_stage"]["solver"] = {
        "kind": "advance_grid",
        "mode": "transient",
        "rtol": 1.0e-10,
        "grid": {"start": 0.0, "stop": 0.1, "dt": 0.01},
    }

    merged_yaml, warnings = merge_config_into_yaml(config, _TWO_STAGE_YAML)
    assert warnings == []

    merged = _parse_output(merged_yaml)
    psr_solver = merged["stages"]["psr_stage"]["solver"]
    assert psr_solver["kind"] == "advance_grid"
    assert psr_solver["mode"] == "transient"
    assert psr_solver["rtol"] == 1.0e-10

    # pfr_stage's solver is untouched, so it stays collapsed to the compact
    # scalar form (kind/mode alone are always re-derivable — no dict needed).
    assert merged["stages"]["pfr_stage"]["solver"] == "advance_to_steady_state"

    # Full round-trip: re-normalizing the merged YAML resolves the new values.
    reparsed = normalize_config(_parse_output(merged_yaml))
    assert reparsed["groups"]["psr_stage"]["solver"]["kind"] == "advance_grid"
    assert reparsed["groups"]["psr_stage"]["solver"]["mode"] == "transient"
    assert (
        reparsed["groups"]["pfr_stage"]["solver"]["kind"] == "advance_to_steady_state"
    )


def test_editing_one_stage_solver_preserves_untouched_fields():
    """max_steps present only in the original YAML survives an rtol-only edit."""
    yaml_with_max_steps = _TWO_STAGE_YAML.replace(
        "      rtol: 1.0e-9\n",
        "      rtol: 1.0e-9\n      max_steps: 5000\n",
    )
    config = normalize_config(_parse(yaml_with_max_steps))

    # Only touch rtol; max_steps should survive since it's still present in
    # the resolved solver dict (normalize_config carries it through).
    solver = dict(config["groups"]["psr_stage"]["solver"])
    solver["rtol"] = 1.0e-11
    config["groups"]["psr_stage"]["solver"] = solver

    merged_yaml, _ = merge_config_into_yaml(config, yaml_with_max_steps)
    merged = _parse_output(merged_yaml)
    psr_solver = merged["stages"]["psr_stage"]["solver"]
    assert psr_solver["rtol"] == 1.0e-11
    assert psr_solver["max_steps"] == 5000


_LEGACY_SOLVE_YAML = """
metadata:
  title: legacy solve syntax test
phases:
  gas:
    mechanism: gri30.yaml
stages:
  torch_stage:
    mechanism: gri30.yaml
    solve: advance
    advance_time: 1.0e-3
  psr_stage:
    mechanism: gri30.yaml
    solve: advance_to_steady_state
torch_stage:
- id: r1
  IdealGasReactor:
    volume: 1 L
psr_stage:
- id: r2
  IdealGasReactor:
    volume: 1 L
"""


def test_kind_only_edit_on_legacy_solve_stage_round_trips_without_crashing():
    """A kind/mode-only edit on a solve: syntax stage stays in solve: form."""
    config = normalize_config(_parse(_LEGACY_SOLVE_YAML))

    # No rtol/atol/max_steps involved — this must collapse back to solve:,
    # not crash trying to .get() a plain kind string (the mirror-step bug).
    config["groups"]["psr_stage"]["solver"] = {
        "kind": "advance",
        "mode": "transient",
        "advance_time": 2.0e-3,
    }

    merged_yaml, warnings = merge_config_into_yaml(config, _LEGACY_SOLVE_YAML)
    assert warnings == []

    merged = _parse_output(merged_yaml)
    psr_stage = merged["stages"]["psr_stage"]
    assert psr_stage["solve"] == "advance"
    assert psr_stage["advance_time"] == 2.0e-3
    assert "solver" not in psr_stage


def test_rtol_edit_on_legacy_solve_stage_warns_instead_of_crashing():
    """An rtol edit on a solve: syntax stage doesn't crash — it warns and drops rtol.

    The legacy solve:/advance_time: syntax has no slot for tolerances; the
    fix is to point the user at the solver: {} block form, not to silently
    lose the value or raise.
    """
    config = normalize_config(_parse(_LEGACY_SOLVE_YAML))
    config["groups"]["torch_stage"]["solver"] = {
        "kind": "advance",
        "mode": "transient",
        "advance_time": 1.0e-3,
        "rtol": 1.0e-10,
    }

    merged_yaml, warnings = merge_config_into_yaml(config, _LEGACY_SOLVE_YAML)

    assert any("torch_stage" in w and "rtol" in w for w in warnings)
    merged = _parse_output(merged_yaml)
    torch_stage = merged["stages"]["torch_stage"]
    assert torch_stage["solve"] == "advance"
    assert "solver" not in torch_stage
