from __future__ import annotations

import cantera as ct  # type: ignore

from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.sim2stone import sim_to_stone_yaml


def test_sim2stone_preserves_energy_off_on_ideal_gas_mole_reactor() -> None:
    """An isothermal (energy="off") IdealGasMoleReactor must round-trip.

    Regression: sim2stone only emitted the ``energy:`` property for
    ``ct.ConstPressureReactor`` instances, so a CSTR built as
    ``ct.IdealGasMoleReactor(gas, energy="off")`` (e.g. the continuous_reactor
    upstream example) silently lost its isothermal setting on conversion —
    the emitted YAML solved as an adiabatic reactor instead.
    """
    gas = ct.Solution("gri30.yaml")
    gas.TPX = 925.0, ct.one_atm, "CH4:0.1, O2:0.2, N2:0.7"

    r = ct.IdealGasMoleReactor(gas, energy="off", volume=1.0, name="R1")
    sim = ct.ReactorNet([r])

    yaml_str = sim_to_stone_yaml(sim, default_mechanism="gri30.yaml")
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    (node,) = [n for n in normalized["nodes"] if n["id"] == "R1"]
    assert str(node["properties"].get("energy")).lower() == "off"


def test_sim2stone_omits_energy_when_default_on() -> None:
    """An energy-on reactor (the default) should not clutter the YAML."""
    gas = ct.Solution("gri30.yaml")
    gas.TPX = 300.0, ct.one_atm, "CH4:1"

    r = ct.IdealGasReactor(gas, name="R1")
    sim = ct.ReactorNet([r])

    yaml_str = sim_to_stone_yaml(sim, default_mechanism="gri30.yaml")
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    (node,) = [n for n in normalized["nodes"] if n["id"] == "R1"]
    assert node["properties"].get("energy") in (None, "on")
