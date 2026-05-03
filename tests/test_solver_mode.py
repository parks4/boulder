"""Tests for solver.mode auto-derivation and validation (Phase 0).

Asserts:
- ``solver.mode`` is auto-derived from ``solver.kind`` for every known kind.
- An explicit ``solver.mode`` that matches ``kind`` is accepted.
- An explicit ``solver.mode`` that contradicts ``kind`` raises ``ValueError``.
- ``groups.<id>.solver["mode"]`` is always set after ``normalize_config``
  for both single-stage (network:) and multi-stage (stages:) files.
"""

import pytest
import yaml

from boulder.config import _resolve_and_validate_solver_mode, normalize_config


def _parse(yaml_str: str):
    """Parse a YAML string into a dict for normalize_config."""
    return yaml.safe_load(yaml_str)

# ---------------------------------------------------------------------------
# Unit tests for the helper directly
# ---------------------------------------------------------------------------

_KIND_TO_MODE = [
    ("advance_to_steady_state", "steady"),
    ("solve_steady", "steady"),
    ("advance", "transient"),
    ("advance_grid", "transient"),
    ("micro_step", "transient"),
]


@pytest.mark.parametrize("kind,expected_mode", _KIND_TO_MODE)
def test_mode_derived_from_kind(kind, expected_mode):
    """solver.mode is auto-derived correctly for every documented kind."""
    result = _resolve_and_validate_solver_mode({"kind": kind}, f"stage '{kind}'")
    assert result["mode"] == expected_mode


@pytest.mark.parametrize("kind,mode", _KIND_TO_MODE)
def test_explicit_mode_matching_kind_accepted(kind, mode):
    """An explicit solver.mode that matches the implied mode is accepted."""
    result = _resolve_and_validate_solver_mode({"kind": kind, "mode": mode}, "test")
    assert result["mode"] == mode


@pytest.mark.parametrize(
    "kind,wrong_mode",
    [
        ("advance_to_steady_state", "transient"),
        ("solve_steady", "transient"),
        ("advance", "steady"),
        ("advance_grid", "steady"),
        ("micro_step", "steady"),
    ],
)
def test_contradicting_mode_raises(kind, wrong_mode):
    """A contradicting solver.mode raises ValueError with both names in the message."""
    with pytest.raises(ValueError) as exc_info:
        _resolve_and_validate_solver_mode({"kind": kind, "mode": wrong_mode}, "ctx")
    msg = str(exc_info.value)
    assert kind in msg
    assert wrong_mode in msg


def test_invalid_mode_string_raises():
    """A mode value that is not 'steady' or 'transient' raises ValueError."""
    with pytest.raises(ValueError, match="not valid"):
        _resolve_and_validate_solver_mode({"kind": "advance_grid", "mode": "unknown"}, "ctx")


def test_missing_kind_defaults_to_steady():
    """With no kind specified, mode defaults to 'steady' (advance_to_steady_state implied)."""
    result = _resolve_and_validate_solver_mode({}, "default")
    assert result["mode"] == "steady"


# ---------------------------------------------------------------------------
# Integration tests via normalize_config
# ---------------------------------------------------------------------------

_MINIMAL_NETWORK_YAML = """
metadata:
  title: mode test
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_grid
    grid:
      start: 0.0
      stop: 0.1
      dt: 0.01
network:
- id: r1
  IdealGasReactor:
    volume: 1 L
"""

_MINIMAL_STAGED_YAML = """
metadata:
  title: staged mode test
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: solve_steady
stages:
  psr:
    mechanism: gri30.yaml
    solver:
      kind: advance_grid
      grid:
        start: 0.0
        stop: 0.1
        dt: 0.01
psr:
- id: r1
  IdealGasReactor:
    volume: 1 L
"""

_MINIMAL_STAGED_GLOBAL_ONLY_YAML = """
metadata:
  title: staged global solver
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: solve_steady
stages:
  psr:
    mechanism: gri30.yaml
    solver:
      kind: solve_steady
psr:
- id: r1
  IdealGasReactor:
    volume: 1 L
"""


def test_network_yaml_mode_resolved():
    """After normalize_config on a single-stage YAML, groups.default.solver has mode."""
    cfg = normalize_config(_parse(_MINIMAL_NETWORK_YAML))
    solver = cfg["groups"]["default"]["solver"]
    assert solver["mode"] == "transient"
    assert solver["kind"] == "advance_grid"


def test_staged_yaml_per_stage_mode_resolved():
    """Per-stage solver.mode overrides the global default."""
    cfg = normalize_config(_parse(_MINIMAL_STAGED_YAML))
    solver = cfg["groups"]["psr"]["solver"]
    assert solver["mode"] == "transient"
    assert solver["kind"] == "advance_grid"


def test_staged_yaml_global_solver_mode_resolved():
    """When a stage-level solver matches global, the mode is properly resolved."""
    cfg = normalize_config(_parse(_MINIMAL_STAGED_GLOBAL_ONLY_YAML))
    solver = cfg["groups"]["psr"]["solver"]
    assert solver["mode"] == "steady"
    assert solver["kind"] == "solve_steady"


def test_no_solver_block_defaults_steady():
    """With no solver block at all, mode defaults to 'steady'."""
    raw = """
metadata:
  title: bare
phases:
  gas:
    mechanism: gri30.yaml
network:
- id: r1
  IdealGasReactor:
    volume: 1 L
"""
    cfg = normalize_config(_parse(raw))
    solver = cfg["groups"]["default"]["solver"]
    assert solver["mode"] == "steady"
    assert solver["kind"] == "advance_to_steady_state"


def test_explicit_correct_mode_in_yaml_accepted():
    """An explicit correct solver.mode in the YAML is accepted without error."""
    raw = """
metadata:
  title: explicit mode
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    mode: transient
    kind: micro_step
    t_total: 1.0e-7
    chunk_dt: 1.0e-9
    max_dt: 1.0e-10
network:
- id: r1
  ConstPressureReactor:
    initial:
      temperature: 300.0
      pressure: 101325.0
      composition: "N2:1"
"""
    cfg = normalize_config(_parse(raw))
    solver = cfg["groups"]["default"]["solver"]
    assert solver["mode"] == "transient"
    assert solver["kind"] == "micro_step"


def test_contradicting_mode_in_yaml_raises():
    """A YAML with mode: steady but kind: advance_grid raises ValueError at normalize_config."""
    raw = """
metadata:
  title: bad mode
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    mode: steady
    kind: advance_grid
    grid:
      start: 0.0
      stop: 0.1
      dt: 0.01
network:
- id: r1
  IdealGasReactor:
    volume: 1 L
"""
    with pytest.raises(ValueError) as exc_info:
        normalize_config(_parse(raw))
    msg = str(exc_info.value)
    assert "steady" in msg
    assert "advance_grid" in msg
