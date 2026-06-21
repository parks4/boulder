"""Tests for STONE node energy property handling on Cantera reactors."""

from __future__ import annotations

import cantera as ct
import pytest

from boulder.reactor_energy import (
    build_reactor_with_energy,
    energy_ctor_suffix,
    parse_energy_prop,
    validate_explicit_energy,
)


def test_parse_energy_prop_absent():
    """Absent energy key returns not explicit."""
    energy, explicit = parse_energy_prop({})
    assert energy is None
    assert explicit is False


def test_parse_energy_prop_off_string():
    """String 'off' parses to energy off."""
    energy, explicit = parse_energy_prop({"energy": "off"})
    assert energy == "off"
    assert explicit is True


def test_mole_reactor_energy_off():
    """IdealGasConstPressureMoleReactor honours energy: off from props."""
    gas = ct.Solution("gri30.yaml")
    gas.TPX = 1200, 101325, "CH4:1"
    reactor = build_reactor_with_energy(
        ct.IdealGasConstPressureMoleReactor,
        gas,
        props={"energy": "off"},
        clone=True,
        type_name="IdealGasConstPressureMoleReactor",
    )
    assert reactor.energy_enabled is False


def test_reservoir_rejects_explicit_energy():
    """Reservoir with energy: off raises ValueError."""
    with pytest.raises(ValueError, match="not supported"):
        validate_explicit_energy({"energy": "off"}, ct.Reservoir, "Reservoir")


def test_emitter_energy_suffix():
    """Download emitter suffix includes explicit energy."""
    assert energy_ctor_suffix({"energy": "off"}) == ', energy=\'off\''
    assert energy_ctor_suffix({}) == ""
