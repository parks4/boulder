from __future__ import annotations

import cantera as ct  # type: ignore

from boulder.cantera_converter import CanteraConverter
from boulder.config import (
    load_yaml_string_with_comments,
    normalize_config,
    validate_config,
)
from boulder.sim2stone import sim_to_internal_config, sim_to_stone_yaml


def _build_test_network():
    """Create a simple network: two reservoirs -> reactor -> reservoir."""
    gas = ct.Solution("gri30.yaml")

    # Upstream reservoirs with different compositions
    gas.TPX = 300.0, ct.one_atm, "O2:0.21, N2:0.78, AR:0.01"
    res_a = ct.Reservoir(gas, name="Air Reservoir")

    gas.TPX = 300.0, ct.one_atm, "CH4:1"
    res_b = ct.Reservoir(gas, name="Fuel Reservoir")

    # Mixer reactor
    gas.TPX = 300.0, ct.one_atm, "O2:0.21, N2:0.78, AR:0.01"
    mixer = ct.IdealGasReactor(gas, name="Mixer")

    # Downstream sink
    downstream = ct.Reservoir(gas, name="Outlet Reservoir")

    # Flow devices
    mfc1 = ct.MassFlowController(
        res_a, mixer, mdot=res_a.thermo.density * 2.5 / 0.21, name="Air Inlet"
    )
    mfc2 = ct.MassFlowController(
        res_b, mixer, mdot=res_b.thermo.density * 1.0, name="Fuel Inlet"
    )
    valve = ct.Valve(mixer, downstream, K=10.0, name="Valve")

    # Only reactors go into ReactorNet (exclude pure reservoirs)
    sim = ct.ReactorNet([mixer])
    return sim, {"mfc1": mfc1, "mfc2": mfc2, "valve": valve}


def test_roundtrip_sim_to_yaml_and_back():
    sim, _ = _build_test_network()

    # Convert sim -> internal config
    internal = sim_to_internal_config(sim, default_mechanism="gri30.yaml")

    # Basic shape checks
    assert (
        len(internal["nodes"]) == 4
    )  # Air Reservoir, Fuel Reservoir, Mixer, Outlet Reservoir
    assert len(internal["connections"]) == 3  # two MFCs + one Valve

    # Serialize to STONE YAML string
    yaml_str = sim_to_stone_yaml(sim, default_mechanism="gri30.yaml")
    loaded_with_comments = load_yaml_string_with_comments(yaml_str)
    normalized = normalize_config(loaded_with_comments)
    validated = validate_config(normalized)

    # Rebuild via CanteraConverter - get mechanism from phases.gas.mechanism (STONE standard)
    phases = validated.get("phases", {})
    gas = phases.get("gas", {}) if isinstance(phases, dict) else {}
    mechanism = gas.get("mechanism", "gri30.yaml")
    converter = CanteraConverter(mechanism=mechanism)
    network, results = converter.build_network(validated)

    # Node parity: same set of reactor IDs
    original_ids = {n["id"] for n in internal["nodes"]}
    rebuilt_ids = set(converter.reactors.keys())
    assert original_ids == rebuilt_ids

    # Connection parity (Flow devices only; Walls would be handled separately)
    original_flow_ids = {
        c["id"]
        for c in internal["connections"]
        if c["type"] in ("MassFlowController", "Valve")
    }
    rebuilt_flow_ids = set(converter.connections.keys())
    assert original_flow_ids == rebuilt_flow_ids

    # ReactorNet parity: one non-reservoir reactor called "Mixer"
    assert len(network.reactors) == 1
    assert network.reactors[0].name == "Mixer"
