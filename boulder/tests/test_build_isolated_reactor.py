"""Tests for DualCanteraConverter.build_isolated_reactor (standalone reactor build)."""

from __future__ import annotations

import cantera as ct

from boulder.cantera_converter import DualCanteraConverter


def _node(props: dict) -> dict:
    return {
        "id": "reactor",
        "type": "IdealGasConstPressureMoleReactor",
        "properties": props,
    }


def test_build_isolated_reactor_sets_state_and_energy_off():
    """State (T, P, X) comes from props and energy: off disables the energy eqn."""
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    reactor, gas = conv.build_isolated_reactor(
        _node(
            {
                "temperature": 1500.0,
                "pressure": 2.0e5,
                "composition": "CH4:1",
                "energy": "off",
            }
        )
    )
    assert isinstance(reactor, ct.IdealGasConstPressureMoleReactor)
    assert reactor.energy_enabled is False
    assert abs(reactor.phase.T - 1500.0) < 1e-6
    assert abs(reactor.phase.P - 2.0e5) < 1.0
    phase = reactor.phase
    assert phase.X[phase.species_index("CH4")] > 0.99


def test_build_isolated_reactor_energy_on_default():
    """Omitting energy leaves the energy equation enabled (Cantera default)."""
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    reactor, _gas = conv.build_isolated_reactor(
        _node({"temperature": 1200.0, "pressure": 1.0e5, "composition": "CH4:1"})
    )
    assert reactor.energy_enabled is True


def test_build_isolated_reactor_accepts_unit_strings_and_volume():
    """Unit-string T/P are coerced to SI and `volume` is honoured."""
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    reactor, _gas = conv.build_isolated_reactor(
        _node(
            {
                "temperature": "1273.15 K",
                "pressure": "1 bar",
                "composition": "CH4:1",
                "volume": 0.25,
            }
        )
    )
    assert abs(reactor.phase.T - 1273.15) < 1e-6
    assert abs(reactor.phase.P - 1.0e5) < 1.0
    assert abs(reactor.volume - 0.25) < 1e-9
