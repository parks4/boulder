"""A stream point feeding several downstream connections splits the upstream flow (#252)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from boulder.runner import BoulderRunner
from boulder.staged_solver import _split_stream_flow

FAN_OUT = """
metadata: {{name: fan_out}}
phases: {{gas: {{mechanism: gri30.yaml}}}}
stages:
  s1: {{solver: advance, advance_time: 0.01}}
  s2: {{solver: advance, advance_time: 0.01}}
s1:
  - id: feed
    Reservoir: {{temperature: 1500 K, pressure: 1 atm, composition: "CH4:0.1, O2:0.2, N2:0.7"}}
  - id: r1
    IdealGasConstPressureReactor: {{volume: 1e-4, energy: "off"}}
  - id: f1
    MassFlowController: {{mass_flow_rate: 0.01 kg/s}}
    source: feed
    target: r1
s2:
  - id: a
    IdealGasConstPressureReactor: {{volume: 1e-4}}
  - id: b
    IdealGasConstPressureReactor: {{volume: 1e-4}}
  - id: r1_a
    MassFlowController: {{{a}}}
    source: r1
    target: a
  - id: r1_b
    MassFlowController: {{{b}}}
    source: r1
    target: b
  - id: a_out
    OutletSink: {{}}
"""


def _build(tmp_path, a: str, b: str):
    path = tmp_path / "fan_out.yaml"
    path.write_text(FAN_OUT.format(a=a, b=b), encoding="utf-8")
    runner = BoulderRunner.from_yaml(str(path))
    runner.build()
    assert runner.converter is not None
    return runner.converter.connections


def test_declared_split_is_kept(tmp_path):
    """Each downstream controller carries its declared share, not the full flow."""
    conns = _build(tmp_path, "mass_flow_rate: 0.004 kg/s", "mass_flow_rate: 0.006 kg/s")
    assert conns["r1_outlet_to_a"].mass_flow_rate == pytest.approx(0.004)
    assert conns["r1_outlet_to_b"].mass_flow_rate == pytest.approx(0.006)
    assert conns["r1_a"].mass_flow_rate == pytest.approx(0.004)


def test_one_undeclared_connection_takes_the_remainder(tmp_path):
    """With one rate declared, the other connection takes what is left."""
    conns = _build(tmp_path, "mass_flow_rate: 0.003 kg/s", "")
    assert conns["r1_outlet_to_a"].mass_flow_rate == pytest.approx(0.003)
    assert conns["r1_outlet_to_b"].mass_flow_rate == pytest.approx(0.007)


def test_declared_rates_that_do_not_add_up_raise(tmp_path):
    """Declared rates that create mass at the stream point raise."""
    with pytest.raises(ValueError, match="add up to 0.012 kg/s, but it receives 0.01"):
        _build(tmp_path, "mass_flow_rate: 0.006 kg/s", "mass_flow_rate: 0.006 kg/s")


def test_two_undeclared_connections_raise(tmp_path):
    """Two undeclared connections leave the split undefined: validation rejects it."""
    with pytest.raises(ValueError, match="Ambiguous conservation"):
        _build(tmp_path, "", "")


def _ic(name, mdot=None):
    props = {} if mdot is None else {"mass_flow_rate": mdot}
    return SimpleNamespace(id=name, source_node="r1", properties=props)


def test_single_connection_takes_the_whole_flow():
    """One undeclared connection keeps the previous behaviour."""
    ic = _ic("x")
    assert _split_stream_flow([ic], 0.02, "r1_outlet") == [(ic, 0.02)]


def test_declared_rates_above_the_flow_with_a_remainder_raise():
    """A remainder would be negative: raise."""
    with pytest.raises(ValueError, match="more than"):
        _split_stream_flow([_ic("x", 0.03), _ic("y")], 0.02, "r1_outlet")


def test_two_undeclared_connections_raise_without_validation():
    """The split itself refuses to guess, for configs that skip validation."""
    with pytest.raises(ValueError, match="declare mass_flow_rate on all of"):
        _split_stream_flow([_ic("x"), _ic("y")], 0.02, "r1_outlet")


def test_a_closed_upstream_hands_off_nothing():
    """No measured outflow (closed upstream reactor): every hand-off carries 0, as before."""
    x, y = _ic("x", 1e-4), _ic("y", 2e-4)
    assert _split_stream_flow([x, y], 0.0, "r1_outlet") == [(x, 0.0), (y, 0.0)]
