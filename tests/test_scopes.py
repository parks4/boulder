"""Tests for boulder/scopes.py — declarative scope observers (Phase C).

Asserts:
- resolve_scope_variable resolves nodes.<id>.T, P, V, mass and species paths.
- resolve_scope_variable raises ValueError for unknown nodes/connections/attributes.
- ScopeRecorder.record() collects (t, value) pairs at each call.
- ScopeRecorder.record() respects the 'every' stride.
- ScopeRecorder.to_dataframes() returns a dict of pandas DataFrames.
- ScopeRecorder.flush_csv() writes a CSV file.
- Integration: a BoulderRunner with scopes: records T for an advance_grid solve.
"""

import os

import pytest
import yaml

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config
from boulder.runner import BoulderRunner
from boulder.scopes import ScopeRecorder, resolve_scope_variable

# ---------------------------------------------------------------------------
# Fixtures: a simple single-reactor converter
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_converter():
    """Build a minimal DualCanteraConverter with one IdealGasReactor."""
    cfg_dict = yaml.safe_load("""
metadata:
  title: scope test
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_to_steady_state
network:
- id: r1
  IdealGasReactor:
    volume: 0.001
    initial:
      temperature: 900.0
      pressure: 101325.0
      composition: "CH4:1, O2:2, N2:7.52"
""")
    cfg = normalize_config(cfg_dict)
    conv = DualCanteraConverter()
    conv.build_network(cfg)
    return conv


# ---------------------------------------------------------------------------
# resolve_scope_variable
# ---------------------------------------------------------------------------


class TestResolveScopeVariable:
    def test_resolves_temperature(self, simple_converter):
        """resolve_scope_variable returns a callable that reads reactor T."""
        getter = resolve_scope_variable("nodes.r1.T", simple_converter)
        val = getter()
        assert isinstance(val, float)
        assert 200.0 < val < 4000.0

    def test_resolves_pressure(self, simple_converter):
        """resolve_scope_variable returns a callable that reads reactor P."""
        getter = resolve_scope_variable("nodes.r1.P", simple_converter)
        val = getter()
        assert isinstance(val, float)
        assert val > 0.0  # physical constraint; combustion changes pressure

    def test_resolves_mole_fraction(self, simple_converter):
        """resolve_scope_variable resolves X[species] paths."""
        getter = resolve_scope_variable("nodes.r1.X[N2]", simple_converter)
        val = getter()
        assert isinstance(val, float)
        assert 0.0 <= val <= 1.0

    def test_resolves_mass_fraction(self, simple_converter):
        """resolve_scope_variable resolves Y[species] paths."""
        getter = resolve_scope_variable("nodes.r1.Y[O2]", simple_converter)
        val = getter()
        assert isinstance(val, float)
        assert 0.0 <= val <= 1.0

    def test_unknown_node_raises(self, simple_converter):
        """resolve_scope_variable raises ValueError for an unknown node."""
        with pytest.raises(ValueError, match="node 'missing' not found"):
            resolve_scope_variable("nodes.missing.T", simple_converter)

    def test_unknown_node_attribute_raises(self, simple_converter):
        """resolve_scope_variable raises ValueError for an unsupported attribute."""
        with pytest.raises(ValueError, match="unsupported node attribute"):
            resolve_scope_variable("nodes.r1.X_total", simple_converter)

    def test_unknown_kind_raises(self, simple_converter):
        """resolve_scope_variable raises ValueError for an unknown kind prefix."""
        with pytest.raises(ValueError, match="unrecognised kind"):
            resolve_scope_variable("network.r1.T", simple_converter)

    def test_too_short_path_raises(self, simple_converter):
        """resolve_scope_variable raises ValueError for a too-short path."""
        with pytest.raises(ValueError, match="at least 3 parts"):
            resolve_scope_variable("nodes.r1", simple_converter)


# ---------------------------------------------------------------------------
# ScopeRecorder
# ---------------------------------------------------------------------------


class TestScopeRecorder:
    def test_record_collects_data(self, simple_converter):
        """ScopeRecorder.record() appends (t, value) for each call."""
        scopes = [{"variable": "nodes.r1.T"}]
        rec = ScopeRecorder(scopes, simple_converter)
        rec.record(0.0)
        rec.record(1.0)
        raw = rec.raw_data
        assert "nodes.r1.T" in raw
        assert len(raw["nodes.r1.T"]) == 2
        ts = [r[0] for r in raw["nodes.r1.T"]]
        assert ts == [0.0, 1.0]

    def test_record_respects_every_stride(self, simple_converter):
        """ScopeRecorder.record() only stores a sample every 'every' calls."""
        scopes = [{"variable": "nodes.r1.T", "every": 3}]
        rec = ScopeRecorder(scopes, simple_converter)
        for i in range(9):
            rec.record(float(i))
        raw = rec.raw_data["nodes.r1.T"]
        assert len(raw) == 3  # 9 / 3 = 3 samples recorded

    def test_to_dataframes_returns_dataframe(self, simple_converter):
        """ScopeRecorder.to_dataframes() returns a dict of DataFrames."""
        pytest.importorskip("pandas")
        scopes = [{"variable": "nodes.r1.T"}]
        rec = ScopeRecorder(scopes, simple_converter)
        rec.record(0.0)
        dfs = rec.to_dataframes()
        assert "nodes.r1.T" in dfs
        df = dfs["nodes.r1.T"]
        assert list(df.columns) == ["t", "value"]
        assert len(df) == 1

    def test_flush_csv_writes_file(self, simple_converter, tmp_path):
        """ScopeRecorder.flush_csv() writes a CSV file for scopes with file:."""
        pytest.importorskip("pandas")
        out_file = str(tmp_path / "T_history.csv")
        scopes = [{"variable": "nodes.r1.T", "file": out_file}]
        rec = ScopeRecorder(scopes, simple_converter)
        rec.record(0.0)
        rec.record(0.5)
        rec.flush_csv()
        assert os.path.exists(out_file)
        with open(out_file) as f:
            content = f.read()
        assert "t" in content
        assert "value" in content

    def test_empty_scopes_block_is_noop(self, simple_converter):
        """ScopeRecorder with None or empty scopes block records nothing."""
        rec = ScopeRecorder(None, simple_converter)
        rec.record(0.0)
        assert rec.raw_data == {}

    def test_unknown_variable_skips_gracefully(self, simple_converter):
        """ScopeRecorder skips scopes with invalid variable paths without raising."""
        scopes = [{"variable": "nodes.nonexistent.T"}]
        rec = ScopeRecorder(scopes, simple_converter)
        rec.record(0.0)
        assert rec.raw_data == {}  # bad scope was silently skipped


# ---------------------------------------------------------------------------
# Integration: BoulderRunner.scopes after advance_grid solve
# ---------------------------------------------------------------------------

_YAML_ADVANCE_GRID_WITH_SCOPES = """
metadata:
  title: scope integration test
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_grid
    grid:
      start: 0.0
      stop: 0.01
      dt: 0.002
scopes:
  - variable: nodes.r1.T
    output: true
  - variable: nodes.r1.P
    output: true
network:
- id: r1
  IdealGasReactor:
    volume: 0.001
    initial:
      temperature: 900.0
      pressure: 101325.0
      composition: "CH4:1, O2:2, N2:7.52"
"""


class TestScopesIntegration:
    def test_boulder_runner_scopes_populated(self):
        """BoulderRunner.scopes returns non-empty DataFrames after an advance_grid solve."""
        pytest.importorskip("pandas")
        cfg = normalize_config(yaml.safe_load(_YAML_ADVANCE_GRID_WITH_SCOPES))
        runner = BoulderRunner(cfg)
        runner.build()
        scopes = runner.scopes
        assert "nodes.r1.T" in scopes
        assert "nodes.r1.P" in scopes
        # Each scope should have at least one row (one per grid step + one at end)
        assert len(scopes["nodes.r1.T"]) >= 1

    def test_boulder_runner_exposed_inputs_is_dict(self):
        """BoulderRunner.exposed_inputs returns a dict (Phase E prep)."""
        cfg = normalize_config(yaml.safe_load(_YAML_ADVANCE_GRID_WITH_SCOPES))
        runner = BoulderRunner(cfg)
        runner.build()
        assert isinstance(runner.exposed_inputs, dict)

    def test_exposed_inputs_unbound_signal_is_exposed(self):
        """A signal with no binding entry appears in exposed_inputs.

        Asserts that a signal declared in signals: but absent from bindings:
        is returned by BoulderRunner.exposed_inputs — this is the FMU input
        variable contract (Phase E / FMI_FMU_EXPORT.md Path A).
        """
        raw = (
            _YAML_ADVANCE_GRID_WITH_SCOPES
            + """
signals:
  - id: external_pulse
    kind: Gaussian
    a: 1.0
    t0: 0.005
    sigma: 0.001
"""
        )
        cfg = normalize_config(yaml.safe_load(raw))
        runner = BoulderRunner(cfg)
        runner.build()
        exposed = runner.exposed_inputs
        assert "external_pulse" in exposed, (
            "Unbound signal 'external_pulse' must appear in exposed_inputs"
        )
        assert exposed["external_pulse"]["kind"] == "Gaussian"

    def test_exposed_inputs_bound_signal_is_not_exposed(self):
        """A signal whose id appears as bindings[].source is NOT in exposed_inputs.

        Asserts that binding a signal to an internal network target removes it
        from the FMU-facing exposed_inputs dict.
        """
        raw = (
            _YAML_ADVANCE_GRID_WITH_SCOPES
            + """
signals:
  - id: internal_signal
    kind: Constant
    value: 1.0e-4
bindings:
  - source: internal_signal
    target: nodes.r1.T
"""
        )
        cfg = normalize_config(yaml.safe_load(raw))
        runner = BoulderRunner(cfg)
        runner.build()
        exposed = runner.exposed_inputs
        assert "internal_signal" not in exposed, (
            "Bound signal 'internal_signal' must NOT appear in exposed_inputs"
        )

    def test_exposed_inputs_mixed_signals(self):
        """Only unbound signals appear in exposed_inputs when both kinds are present.

        Asserts that when both bound and unbound signals are declared, only the
        unbound ones appear in exposed_inputs.
        """
        raw = (
            _YAML_ADVANCE_GRID_WITH_SCOPES
            + """
signals:
  - id: bound_sig
    kind: Constant
    value: 1.0e-4
  - id: free_sig
    kind: Gaussian
    a: 1.0
    t0: 0.005
    sigma: 0.001
bindings:
  - source: bound_sig
    target: nodes.r1.T
"""
        )
        cfg = normalize_config(yaml.safe_load(raw))
        runner = BoulderRunner(cfg)
        runner.build()
        exposed = runner.exposed_inputs
        assert "free_sig" in exposed, "Unbound signal must be in exposed_inputs"
        assert "bound_sig" not in exposed, "Bound signal must not be in exposed_inputs"

    def test_exposed_inputs_empty_when_no_signals(self):
        """BoulderRunner.exposed_inputs returns {} when no signals: block is declared."""
        cfg = normalize_config(yaml.safe_load(_YAML_ADVANCE_GRID_WITH_SCOPES))
        runner = BoulderRunner(cfg)
        runner.build()
        assert runner.exposed_inputs == {}

    def test_scope_temperature_values_are_physical(self):
        """Temperature recorded by scopes is between 200 K and 4000 K."""
        pytest.importorskip("pandas")
        cfg = normalize_config(yaml.safe_load(_YAML_ADVANCE_GRID_WITH_SCOPES))
        runner = BoulderRunner(cfg)
        runner.build()
        df = runner.scopes["nodes.r1.T"]
        assert all(200.0 < v < 4000.0 for v in df["value"])

    def test_scope_time_column_increases_monotonically(self):
        """Scope t column increases monotonically."""
        pytest.importorskip("pandas")
        cfg = normalize_config(yaml.safe_load(_YAML_ADVANCE_GRID_WITH_SCOPES))
        runner = BoulderRunner(cfg)
        runner.build()
        df = runner.scopes["nodes.r1.T"]
        if len(df) > 1:
            times = list(df["t"])
            assert times == sorted(times)

    def test_no_scopes_block_returns_empty_dict(self):
        """BoulderRunner.scopes returns {} when no scopes: block is declared."""
        raw = """
metadata:
  title: bare
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_to_steady_state
network:
- id: r1
  IdealGasReactor:
    volume: 0.001
    initial:
      temperature: 900.0
      pressure: 101325.0
      composition: "CH4:1, O2:2, N2:7.52"
"""
        cfg = normalize_config(yaml.safe_load(raw))
        runner = BoulderRunner(cfg)
        runner.build()
        assert runner.scopes == {}
