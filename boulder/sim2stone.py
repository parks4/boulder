"""Conversion utilities: Cantera ReactorNet -> STONE YAML configuration.

This module inspects a resolved Cantera network (``ct.ReactorNet``) and emits a
configuration compatible with Boulder/STONE. The conversion attempts to be
round-trippable: building a network from the emitted YAML should yield an
equivalent topology (same nodes and connections) when reconstructed by
``CanteraConverter``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

import cantera as ct  # type: ignore

from .config import CANTERA_MECHANISM, yaml_to_string_with_comments
from .ctutils import collect_all_reactors_and_reservoirs


def _composition_to_string(thermo: ct.ThermoPhase, min_fraction: float = 1e-12) -> str:
    """Serialize the current mole fractions to a compact composition string.

    Parameters
    ----------
    thermo
        A Cantera ThermoPhase (e.g., ``reactor.thermo``).
    min_fraction
        Species with mole fraction below this threshold are omitted to keep the
        output readable.
    """
    species: List[str] = list(thermo.species_names)
    X: List[float] = list(thermo.X)

    # Filter near-zero entries for readability while preserving normalization.
    items: List[Tuple[str, float]] = [
        (name, float(val))
        for name, val in zip(species, X)
        if float(val) >= min_fraction
    ]
    if not items:
        # Fallback when all are below threshold
        return "N2:1"

    # Sort by descending fraction for stability
    items.sort(key=lambda it: it[1], reverse=True)
    return ",".join([f"{name}:{value:g}" for name, value in items])


def _infer_node_type(reactor: ct.Reactor) -> str:
    """Map a Cantera reactor instance to a Boulder component type string."""
    # Explicit checks for common types we support out-of-the-box
    if isinstance(reactor, ct.Reservoir):
        return "Reservoir"
    if isinstance(reactor, ct.IdealGasReactor):
        return "IdealGasReactor"
    # Fallback to class name for supported custom/reactor variants
    return type(reactor).__name__


def _infer_connection_type(device: ct.FlowDevice) -> str:
    """Map a Cantera flow device to a Boulder connection type string."""
    if isinstance(device, ct.MassFlowController):
        return "MassFlowController"
    if isinstance(device, ct.Valve):
        return "Valve"
    return type(device).__name__


def _unique_flow_devices(all_reactors: Set[ct.Reactor]) -> Set[ct.FlowDevice]:
    """Collect a unique set of flow devices from all reactors in the network."""
    devices: Set[ct.FlowDevice] = set()
    for r in all_reactors:
        # Both inlets and outlets are FlowDevice instances
        for dev in list(getattr(r, "inlets", [])) + list(getattr(r, "outlets", [])):
            devices.add(dev)
    return devices


def _unique_walls(all_reactors: Set[ct.Reactor]) -> Set[ct.Wall]:
    """Collect a unique set of walls from all reactors in the network."""
    walls: Set[ct.Wall] = set()
    for r in all_reactors:
        for w in getattr(r, "walls", []):
            walls.add(w)
    return walls


def sim_to_internal_config(
    sim: ct.ReactorNet, default_mechanism: Optional[str] = None
) -> Dict[str, Any]:
    """Convert a Cantera ReactorNet to Boulder internal configuration format.

    The returned config uses the normalized internal format consumed by
    ``CanteraConverter.build_network``.
    """
    mechanism = default_mechanism or CANTERA_MECHANISM

    # Collect unique reactors/reservoirs from the entire network
    all_reactors = list(collect_all_reactors_and_reservoirs(sim))
    # Deterministic order
    all_reactors.sort(key=lambda r: r.name)

    nodes: List[Dict[str, Any]] = []
    for r in all_reactors:
        node_type = _infer_node_type(r)
        props: Dict[str, Any] = {
            "temperature": float(r.thermo.T),
            "pressure": float(r.thermo.P),
            "composition": _composition_to_string(r.thermo),
        }
        # Optional group propagation if present
        group_name = getattr(r, "group_name", "")
        if isinstance(group_name, str) and group_name:
            props["group"] = group_name

        # Ensure each node has a non-empty unique identifier
        rid = r.name or f"reactor_{id(r)}"
        nodes.append({"id": rid, "type": node_type, "properties": props})

    # Flow devices (MassFlowController, Valve, etc.)
    devices = _unique_flow_devices(set(all_reactors))
    connections: List[Dict[str, Any]] = []
    for dev in sorted(list(devices), key=lambda d: (_infer_connection_type(d), id(d))):
        src = dev.upstream
        tgt = dev.downstream
        src_id = getattr(src, "name", None) or f"reactor_{id(src)}"
        tgt_id = getattr(tgt, "name", None) or f"reactor_{id(tgt)}"

        conn_type = _infer_connection_type(dev)
        props: Dict[str, Any] = {}
        if isinstance(dev, ct.MassFlowController):
            # Prefer attribute if available; Cantera exposes mass_flow_rate as a property
            try:
                props["mass_flow_rate"] = float(dev.mass_flow_rate)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Unable to read mass flow rate for connection {src_id}->{tgt_id}: {exc}"
                ) from exc
        elif isinstance(dev, ct.Valve):
            # Capture valve coefficient if available
            coeff = None
            if hasattr(dev, "valve_coeff"):
                coeff = getattr(dev, "valve_coeff")
            elif hasattr(dev, "K"):
                coeff = getattr(dev, "K")
            if coeff is not None:
                try:
                    props["valve_coeff"] = float(coeff)
                except Exception:
                    pass

        # Create a stable identifier
        name_attr = getattr(dev, "name", None)
        cid = (
            name_attr
            if isinstance(name_attr, str) and name_attr
            else f"{conn_type}_{src_id}_to_{tgt_id}"
        )

        connections.append(
            {
                "id": cid,
                "type": conn_type,
                "properties": props,
                "source": src_id,
                "target": tgt_id,
            }
        )

    # Walls (energy links)
    walls = _unique_walls(set(all_reactors))
    for w in sorted(
        list(walls), key=lambda w: (id(w.left_reactor), id(w.right_reactor))
    ):
        left = w.left_reactor
        right = w.right_reactor
        l_id = getattr(left, "name", None) or f"reactor_{id(left)}"
        r_id = getattr(right, "name", None) or f"reactor_{id(right)}"

        cid = getattr(w, "name", None)
        if not isinstance(cid, str) or not cid:
            cid = f"Wall_{l_id}_to_{r_id}"

        # Convert current heat rate to an equivalent electric power in kW (best effort)
        try:
            q_watts = float(getattr(w, "heat_rate"))
            electric_power_kW = q_watts / 1e3
        except Exception:
            electric_power_kW = 0.0

        connections.append(
            {
                "id": cid,
                "type": "Wall",
                "properties": {
                    "electric_power_kW": electric_power_kW,
                    # Efficiency unknown; preserve neutral defaults used by builder
                    "torch_eff": 1.0,
                    "gen_eff": 1.0,
                },
                "source": l_id,
                "target": r_id,
            }
        )

    internal: Dict[str, Any] = {
        "nodes": nodes,
        "connections": connections,
        "simulation": {"mechanism": mechanism},
    }

    return internal


def sim_to_stone_yaml(
    sim: ct.ReactorNet,
    default_mechanism: Optional[str] = None,
) -> str:
    """Convert a Cantera ReactorNet to a STONE YAML string.

    Includes top-level `phases` (with `gas/mechanism`) and an explicit `settings` section.
    Adds a blank line before `nodes` and `connections` for readability.
    """
    internal = sim_to_internal_config(sim, default_mechanism=default_mechanism)

    # Determine mechanism for phases/gas
    mechanism = (
        (internal.get("simulation") or {}).get("mechanism")
        or default_mechanism
        or CANTERA_MECHANISM
    )

    # Build STONE format using ruamel structures to control formatting
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    stone_cm = CommentedMap()
    # phases
    phases_cm = CommentedMap()
    gas_cm = CommentedMap()
    gas_cm["mechanism"] = mechanism
    phases_cm["gas"] = gas_cm
    stone_cm["phases"] = phases_cm

    # settings (explicit section even if empty)
    stone_cm["settings"] = CommentedMap()

    # nodes
    nodes_seq = CommentedSeq()
    for node in internal.get("nodes", []):
        node_cm = CommentedMap()
        node_cm["id"] = node["id"]
        node_cm[node["type"]] = node.get("properties", {})
        nodes_seq.append(node_cm)
    stone_cm["nodes"] = nodes_seq
    # blank line before nodes
    try:
        stone_cm.yaml_set_comment_before_after_key("nodes", before="\n")
    except Exception:
        pass

    # connections
    conns_seq = CommentedSeq()
    for conn in internal.get("connections", []):
        conn_cm = CommentedMap()
        conn_cm["id"] = conn["id"]
        conn_cm[conn["type"]] = conn.get("properties", {})
        conn_cm["source"] = conn["source"]
        conn_cm["target"] = conn["target"]
        conns_seq.append(conn_cm)
    stone_cm["connections"] = conns_seq
    # blank line before connections
    try:
        stone_cm.yaml_set_comment_before_after_key("connections", before="\n")
    except Exception:
        pass

    return yaml_to_string_with_comments(stone_cm)


def write_sim_as_yaml(
    sim: ct.ReactorNet,
    file_path: str,
    default_mechanism: Optional[str] = None,
) -> None:
    """Serialize a Cantera ReactorNet to a STONE YAML file."""
    yaml_str = sim_to_stone_yaml(sim, default_mechanism=default_mechanism)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)
