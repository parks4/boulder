"""Conversion utilities: Cantera ReactorNet -> STONE YAML configuration.

This module inspects a resolved Cantera network (``ct.ReactorNet``) and emits a
configuration compatible with Boulder/STONE. The conversion attempts to be
round-trippable: building a network from the emitted YAML should yield an
equivalent topology (same nodes and connections) when reconstructed by
``CanteraConverter``.
"""

from __future__ import annotations

import ast
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import cantera as ct  # type: ignore

from .config import CANTERA_MECHANISM, yaml_to_string_with_comments
from .ctutils import collect_all_reactors_and_reservoirs


def _parse_python_comments(source_file: str) -> Dict[str, Any]:
    """Parse Python source file to extract comments and metadata.

    Returns a dictionary with file-level metadata and variable-specific comments.
    """
    if not os.path.isfile(source_file):
        return {}

    try:
        with open(source_file, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception:
        return {}

    metadata = {
        "file_description": "",
        "variable_comments": {},
        "source_file": os.path.basename(source_file),
    }

    # Extract docstring as file description
    try:
        tree = ast.parse(source_code)
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            metadata["file_description"] = tree.body[0].value.value.strip()
    except Exception:
        pass

    # Parse line-by-line for variable comments
    lines = source_code.split("\n")
    for i, line in enumerate(lines):
        # Look for variable assignments with comments
        if "=" in line and "#" in line:
            # Extract variable name and comment
            parts = line.split("#", 1)
            if len(parts) == 2:
                var_part = parts[0].strip()
                comment = parts[1].strip()

                # Extract variable name (simple heuristic)
                var_match = re.match(r"(\w+)\s*=", var_part)
                if var_match:
                    var_name = var_match.group(1)
                    metadata["variable_comments"][var_name] = comment

        # Look for standalone comments above variable assignments
        elif line.strip().startswith("#") and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if "=" in next_line and "#" not in next_line:
                comment = line.strip()[1:].strip()
                var_match = re.match(r"(\w+)\s*=", next_line)
                if var_match:
                    var_name = var_match.group(1)
                    if var_name not in metadata["variable_comments"]:
                        metadata["variable_comments"][var_name] = comment

    return metadata


def _mechanism_from_thermo(thermo: ct.ThermoPhase) -> Optional[str]:
    """Try to read the mechanism file name from the ThermoPhase.

    Prefer attributes exposed by Cantera (e.g., `source`, `input_name`). Returns
    a basename like 'gri30.yaml' when possible.
    """
    for attr in ("source", "input_name"):
        val = getattr(thermo, attr, None)
        if isinstance(val, str) and val:
            base = os.path.basename(val)
            return base or val
    return None


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
    sim: ct.ReactorNet,
    default_mechanism: Optional[str] = None,
    source_file: Optional[str] = None,
    include_comments: bool = True,
) -> Dict[str, Any]:
    """Convert a Cantera ReactorNet to Boulder internal configuration format.

    The returned config uses the normalized internal format consumed by
    ``CanteraConverter.build_network``.
    """
    mechanism = default_mechanism or CANTERA_MECHANISM

    # Parse comments and metadata from source file if provided
    metadata = {}
    if source_file and include_comments:
        metadata = _parse_python_comments(source_file)

    # Collect unique reactors/reservoirs from the entire network
    all_reactors = list(collect_all_reactors_and_reservoirs(sim))
    # Deterministic order
    all_reactors.sort(key=lambda r: r.name)

    nodes: List[Dict[str, Any]] = []
    for r in all_reactors:
        node_type = _infer_node_type(r)
        # Capture mechanism override if present on reactor object (set by builder)
        mech_override = getattr(r, "_boulder_mechanism", None)

        props: Dict[str, Any] = {
            "temperature": float(r.thermo.T),
            "pressure": float(r.thermo.P),
            "composition": _composition_to_string(r.thermo),
        }

        # Add volume for non-Reservoir reactors (Reservoirs have infinite volume)
        if not isinstance(r, ct.Reservoir):
            try:
                volume = float(r.volume)
                if volume > 0:  # Only include positive volumes
                    props["volume"] = volume
            except (AttributeError, ValueError, TypeError):
                # Volume attribute may not be available or accessible
                pass
        if isinstance(mech_override, str) and mech_override:
            props["mechanism"] = mech_override
        else:
            guessed = _mechanism_from_thermo(r.thermo)
            if guessed:
                props["mechanism"] = guessed
        # Optional group propagation if present
        group_name = getattr(r, "group_name", "")
        if isinstance(group_name, str) and group_name:
            props["group"] = group_name

        # Ensure each node has a non-empty unique identifier
        rid = r.name or f"reactor_{id(r)}"

        # Add description from comments if available
        node_dict = {"id": rid, "type": node_type, "properties": props}
        if metadata and "variable_comments" in metadata:
            # Look for comments associated with this reactor's variable name
            var_comments = metadata["variable_comments"]
            for var_name, comment in var_comments.items():
                if var_name in rid or rid in var_name:
                    node_dict["description"] = comment
                    break

        nodes.append(node_dict)

    # Flow devices (MassFlowController, Valve, etc.)
    devices = _unique_flow_devices(set(all_reactors))
    connections: List[Dict[str, Any]] = []
    for dev in sorted(list(devices), key=lambda d: (_infer_connection_type(d), id(d))):
        src = dev.upstream
        tgt = dev.downstream
        src_id = getattr(src, "name", None) or f"reactor_{id(src)}"
        tgt_id = getattr(tgt, "name", None) or f"reactor_{id(tgt)}"

        conn_type = _infer_connection_type(dev)
        conn_props: Dict[str, Any] = {}
        if isinstance(dev, ct.MassFlowController):
            # Prefer attribute if available; Cantera exposes mass_flow_rate as a property
            try:
                props["mass_flow_rate"] = float(dev.mass_flow_rate)
            except Exception:
                # Fallbacks: some backends require initialized networks; try alternate attributes
                mdot_attr = getattr(dev, "mdot", None)
                try:
                    mdot_value = mdot_attr() if callable(mdot_attr) else mdot_attr
                except Exception:
                    mdot_value = None
                if isinstance(mdot_value, (int, float)):
                    props["mass_flow_rate"] = float(mdot_value)
                # Else: omit property; builder will use its default
            # If mass flow is negative, re-orient the connection and take absolute value
            mfr = conn_props.get("mass_flow_rate")
            if isinstance(mfr, (int, float)) and mfr < 0:
                conn_props["mass_flow_rate"] = abs(float(mfr))
                # swap
                src_id, tgt_id = tgt_id, src_id
        elif isinstance(dev, ct.Valve):
            # Capture valve coefficient if available
            coeff = None
            if hasattr(dev, "valve_coeff"):
                coeff = getattr(dev, "valve_coeff")
            elif hasattr(dev, "K"):
                coeff = getattr(dev, "K")
            if coeff is not None:
                try:
                    conn_props["valve_coeff"] = float(coeff)
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
                "properties": conn_props,
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

        cid_raw = getattr(w, "name", None)
        if not isinstance(cid_raw, str) or not cid_raw:
            cid = f"Wall_{l_id}_to_{r_id}"
        else:
            cid = cid_raw

        # Convert current heat rate to an equivalent electric power in kW (best effort)
        try:
            q_watts = float(getattr(w, "heat_rate"))
        except Exception:
            q_watts = 0.0
        # If heat flows from right to left (negative), invert orientation and use positive magnitude
        if q_watts < 0:
            electric_power_kW = (-q_watts) / 1e3
            l_id, r_id = r_id, l_id
        else:
            electric_power_kW = q_watts / 1e3

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
        "phases": {"gas": {"mechanism": mechanism}},
    }

    # Add metadata if available
    if metadata:
        file_metadata = {
            "title": f"Converted from {metadata.get('source_file', 'Python script')}",
            "description": metadata.get("file_description", ""),
            "source_file": metadata.get("source_file", ""),
        }
        # Only include non-empty metadata
        file_metadata = {k: v for k, v in file_metadata.items() if v}
        if file_metadata:
            internal["metadata"] = file_metadata

    return internal


def sim_to_stone_yaml(
    sim: ct.ReactorNet,
    default_mechanism: Optional[str] = None,
    source_file: Optional[str] = None,
    include_comments: bool = True,
) -> str:
    """Convert a Cantera ReactorNet to a STONE YAML string.

    Includes top-level `phases` (with `gas/mechanism`) and an explicit `settings` section.
    Adds a blank line before `nodes` and `connections` for readability.
    """
    internal = sim_to_internal_config(
        sim,
        default_mechanism=default_mechanism,
        source_file=source_file,
        include_comments=include_comments,
    )

    # Determine mechanism from phases.gas.mechanism (STONE standard)
    phases = internal.get("phases", {})
    gas = phases.get("gas", {}) if isinstance(phases, dict) else {}
    mechanism = gas.get("mechanism") or default_mechanism or CANTERA_MECHANISM

    # Build STONE format using ruamel structures to control formatting
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    stone_cm = CommentedMap()

    # metadata (if available)
    if "metadata" in internal:
        metadata_cm = CommentedMap()
        for key, value in internal["metadata"].items():
            if key == "description" and isinstance(value, str) and "\n" in value:
                # Use literal block style for multi-line descriptions
                from ruamel.yaml.scalarstring import LiteralScalarString

                metadata_cm[key] = LiteralScalarString(value)
            else:
                metadata_cm[key] = value
        stone_cm["metadata"] = metadata_cm

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
        # Copy properties to avoid mutating internal
        props = dict(node.get("properties", {}) or {})
        # Extract per-node mechanism and emit at node level (not inside class block)
        node_mech = props.pop("mechanism", None)
        # Drop per-node mechanism if it matches the global phases gas mechanism
        if node_mech == mechanism:
            node_mech = None
        node_cm[node["type"]] = props
        if node_mech is not None:
            node_cm["mechanism"] = node_mech
        # Add description if available
        if "description" in node:
            desc = node["description"]
            if isinstance(desc, str) and "\n" in desc:
                from ruamel.yaml.scalarstring import LiteralScalarString

                node_cm["description"] = LiteralScalarString(desc)
            else:
                node_cm["description"] = desc
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
    source_file: Optional[str] = None,
    include_comments: bool = True,
) -> None:
    """Serialize a Cantera ReactorNet to a STONE YAML file."""
    yaml_str = sim_to_stone_yaml(
        sim,
        default_mechanism=default_mechanism,
        source_file=source_file,
        include_comments=include_comments,
    )
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)
