from __future__ import annotations

import cantera as ct  # type: ignore

from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.sim2stone import sim_to_stone_yaml


def test_sim2stone_preserves_per_node_mechanisms() -> None:
    """Two reactors using different mechanisms should be preserved in YAML.

    R1 uses air.yaml; R2 uses gri30.yaml. The emitted STONE YAML should carry
    node-level mechanism overrides that survive normalization.
    """
    gas_air = ct.Solution("air.yaml")
    gas_gri = ct.Solution("gri30.yaml")

    gas_air.TPX = 300.0, ct.one_atm, "N2:0.78,O2:0.21,AR:0.01"
    gas_gri.TPX = 300.0, ct.one_atm, "CH4:1"

    # clone=False: Cantera 4 clones the contents by default, and a cloned
    # Solution loses its `source` (the serializer's mechanism inference).
    r1 = ct.IdealGasReactor(gas_air, name="R1", clone=False)
    r2 = ct.IdealGasReactor(gas_gri, name="R2", clone=False)

    # Hint serializer if supported
    try:
        r1._boulder_mechanism = "air.yaml"  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        r2._boulder_mechanism = "gri30.yaml"  # type: ignore[attr-defined]
    except Exception:
        pass

    sim = ct.ReactorNet([r1, r2])

    # Use default equal to air.yaml so only R2 requires a per-node override
    yaml_str = sim_to_stone_yaml(sim, default_mechanism="air.yaml")
    loaded = load_yaml_string_with_comments(yaml_str)
    normalized = normalize_config(loaded)

    mech_by_id = {
        node["id"]: node["properties"].get("mechanism") for node in normalized["nodes"]
    }
    # Get global mechanism from phases.gas.mechanism (STONE standard)
    phases = normalized.get("phases", {})
    gas = phases.get("gas", {}) if isinstance(phases, dict) else {}
    global_mech = gas.get("mechanism")

    # R1 matches global, so mechanism may be omitted at node level
    assert global_mech == "air.yaml"
    assert mech_by_id.get("R1") is None  # because is equal to global "air.yaml"

    # R2 uses gri30, so mechanism override must be present at node level after normalization
    assert mech_by_id.get("R2") == "gri30.yaml"


def test_sim2stone_preserves_non_default_phase_name() -> None:
    """A reactor built from a non-default named phase gets a '#phase' suffix.

    Regression: nDodecane_Reitz.yaml's file-order-default phase uses a
    Redlich-Kwong equation of state; the ideal-gas phase used by
    fuel_injection.py-style examples is a *named* phase ("nDodecane_IG").
    _mechanism_from_thermo previously read only the file path, silently
    dropping the phase name -- rebuilding from the emitted YAML picked
    Redlich-Kwong by default and IdealGasReactor construction failed
    outright ("Incompatible phase type 'Redlich-Kwong' provided").
    """
    gas = ct.Solution("nDodecane_Reitz.yaml", "nDodecane_IG", transport_model=None)
    gas.TPX = 300.0, ct.one_atm, "c12h26:1"
    r = ct.IdealGasReactor(gas, name="R1", clone=False)
    sim = ct.ReactorNet([r])

    # Pass the bare file name as default_mechanism (no #phase suffix) --
    # matching how upstream callers that don't already know the phase name
    # invoke sim2stone.
    yaml_str = sim_to_stone_yaml(sim, default_mechanism="nDodecane_Reitz.yaml")
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    mech_by_id = {
        node["id"]: node["properties"].get("mechanism") for node in normalized["nodes"]
    }
    assert mech_by_id.get("R1") == "nDodecane_Reitz.yaml#nDodecane_IG"
