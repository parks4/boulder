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

    r1 = ct.IdealGasReactor(gas_air, name="R1")
    r2 = ct.IdealGasReactor(gas_gri, name="R2")

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

    mech_by_id = {node["id"]: node["properties"].get("mechanism") for node in normalized["nodes"]}
    global_mech = normalized.get("simulation", {}).get("mechanism", None)

    # R1 matches global, so mechanism may be omitted at node level
    assert global_mech == "air.yaml"
    assert mech_by_id.get("R1") is None  # because is equal to global "air.yaml"

    # R2 uses gri30, so mechanism override must be present at node level after normalization
    assert mech_by_id.get("R2") == "gri30.yaml"


