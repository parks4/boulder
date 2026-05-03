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
from pathlib import Path
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

    metadata: Dict[str, Any] = {
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


def _smart_extract_object_comments(
    source_file: str, reactor_net: ct.ReactorNet
) -> Dict[str, str]:
    """Smart extraction of comments for reactor network objects.

    Uses the reactor network to identify objects, then parses the Python source
    to find comments above their definitions.

    Args:
        source_file: Path to the Python source file
        reactor_net: The Cantera ReactorNet object

    Returns
    -------
        Dictionary mapping object names to their descriptions
    """
    if not os.path.isfile(source_file):
        return {}

    try:
        with open(source_file, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception:
        return {}

    # Collect all objects from the reactor network
    all_reactors = list(collect_all_reactors_and_reservoirs(reactor_net))
    flow_devices = _unique_flow_devices(set(all_reactors))
    walls = _unique_walls(set(all_reactors))

    # Create mapping of object names to look for
    object_names = set()

    # Add reactor names
    for reactor in all_reactors:
        if hasattr(reactor, "name") and reactor.name:
            object_names.add(reactor.name)

    # Add flow device names
    for device in flow_devices:
        if hasattr(device, "name") and device.name:
            object_names.add(device.name)

    # Add wall names
    for wall in walls:
        if hasattr(wall, "name") and wall.name:
            object_names.add(wall.name)

    # Parse the source code to find variable assignments and their comments
    lines = source_code.split("\n")
    object_comments: Dict[str, str] = {}

    # First pass: collect all comment blocks and their positions
    comment_blocks: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line_stripped = lines[i].strip()

        # Look for comment blocks
        if line_stripped.startswith("#"):
            comments = []

            # Collect all consecutive comment lines
            while i < len(lines) and lines[i].strip().startswith("#"):
                comment_text = lines[i].strip()[1:].strip()
                # Skip empty comments and %% section markers, but keep regular comments
                if comment_text and not (
                    comment_text.startswith("%%") and len(comment_text.strip()) <= 2
                ):
                    # Remove %% prefix if present but keep the content
                    if comment_text.startswith("%%"):
                        comment_text = comment_text[2:].strip()
                    if comment_text:  # Only add non-empty comments
                        comments.append(comment_text)
                i += 1

            # Skip empty lines after comments
            while i < len(lines) and not lines[i].strip():
                i += 1

            if comments:
                comment_blocks.append(
                    {"comments": comments, "end_line": i - 1, "next_code_line": i}
                )
        else:
            i += 1

    # Second pass: find Cantera object assignments and associate with comment blocks
    for i, line in enumerate(lines):
        line_stripped = line.strip()

        # Skip empty lines and comments
        if not line_stripped or line_stripped.startswith("#"):
            continue

        # Look for assignments that create Cantera objects
        if (
            "=" in line
            and ("ct." in line or "cantera." in line)
            and any(
                cantera_type in line
                for cantera_type in [
                    "Reservoir",
                    "IdealGasReactor",
                    "MassFlowController",
                    "Valve",
                    "Wall",
                    "Solution",
                ]
            )
        ):
            # Extract variable name
            var_match = re.match(r"(\w+)\s*=", line_stripped)
            if var_match:
                var_name = var_match.group(1)

                # Find the most recent comment block before this line
                relevant_comment_block = None
                for block in comment_blocks:
                    if block["next_code_line"] <= i:
                        # Check if this line is within reasonable distance of the comment block
                        if i - block["next_code_line"] <= 5:  # Allow up to 5 lines gap
                            relevant_comment_block = block

                if relevant_comment_block:
                    description = "\n".join(relevant_comment_block["comments"])
                    object_comments[var_name] = description

                    # Also try to match by object name if it has one
                    # Look for name= parameter in the line
                    name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', line)
                    if name_match:
                        object_name = name_match.group(1)
                        object_comments[object_name] = description

    return object_comments


def _mechanism_from_thermo(thermo: ct.ThermoPhase) -> Optional[str]:
    """Read mechanism path from the ThermoPhase for STONE ``mechanism:`` fields.

    Cantera resolves mechanisms under its ``data`` directory; paths like
    ``example_data/methane-plasma-pavan-2023.yaml`` must be preserved. We only
    reduce to a bare filename when *val* is already a single path component or
    when an absolute install path is trimmed to the relative tail after the
    ``data`` directory (matching how ``ct.Solution('gri30.yaml')`` is stored).
    """
    for attr in ("source", "input_name"):
        val = getattr(thermo, attr, None)
        if not isinstance(val, str) or not val:
            continue
        p = Path(val)
        parts = p.parts
        parts_lower = tuple(x.lower() for x in parts)
        if p.is_absolute():
            try:
                idx = parts_lower.index("data")
            except ValueError:
                return p.name
            tail = Path(*parts[idx + 1 :])
            return tail.as_posix()
        if len(parts) > 1:
            return p.as_posix()
        return p.name
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
    if isinstance(reactor, ct.ConstPressureReactor):
        return "ConstPressureReactor"
    if isinstance(reactor, ct.IdealGasReactor):
        return "IdealGasReactor"
    # Fallback to class name for supported custom/reactor variants
    return type(reactor).__name__


def _infer_connection_type(device: ct.FlowDevice) -> str:
    """Map a Cantera flow device to a Boulder connection type string."""
    if isinstance(device, ct.MassFlowController):
        return "MassFlowController"
    if isinstance(device, ct.PressureController):
        return "PressureController"
    if isinstance(device, ct.Valve):
        return "Valve"
    return type(device).__name__


def _stone_flow_connection_ids(dev: ct.FlowDevice) -> Tuple[str, str, str, str]:
    """Return ``(cid, conn_type, source_node_id, target_node_id)`` for a flow device."""
    src = dev.upstream
    tgt = dev.downstream
    src_id = getattr(src, "name", None) or f"reactor_{id(src)}"
    tgt_id = getattr(tgt, "name", None) or f"reactor_{id(tgt)}"
    conn_type = _infer_connection_type(dev)
    name_attr = getattr(dev, "name", None)
    cid = (
        name_attr
        if isinstance(name_attr, str) and name_attr
        else f"{conn_type}_{src_id}_to_{tgt_id}"
    )
    return cid, conn_type, src_id, tgt_id


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
    object_comments = {}
    if source_file and include_comments:
        metadata = _parse_python_comments(source_file)
        # Use smart extraction to get comments for reactor network objects
        object_comments = _smart_extract_object_comments(source_file, sim)

    # Cantera flow devices expose mass_flow_rate only after the ReactorNet has been
    # initialized (i.e. after the first advance/step call).  Calling advance(0.0) on
    # a fresh network triggers the lazy C++ initialization without changing any state.
    try:
        sim.advance(sim.time)
    except Exception:
        pass

    # Collect unique reactors/reservoirs from the entire network
    all_reactors = list(collect_all_reactors_and_reservoirs(sim))
    # Deterministic order
    all_reactors.sort(key=lambda r: r.name)

    nodes: List[Dict[str, Any]] = []
    for r in all_reactors:
        node_type = _infer_node_type(r)
        # Capture mechanism override if present on reactor object (set by builder)
        mech_override = getattr(r, "_boulder_mechanism", None)

        if isinstance(r, ct.Reservoir):
            # Reservoirs are boundary conditions; capture T, P, and composition so
            # STONE v2 and DualCanteraConverter agree (Reservoir requires explicit P).
            props: Dict[str, Any] = {
                "temperature": float(r.thermo.T),
                "pressure": float(r.thermo.P),
                "composition": _composition_to_string(r.thermo),
            }
        else:
            props = {
                "temperature": float(r.thermo.T),
                "pressure": float(r.thermo.P),
                "composition": _composition_to_string(r.thermo),
            }

            # Volume (Reservoirs have infinite / undefined volume)
            try:
                volume = float(r.volume)
                if volume > 0:  # Only include positive volumes
                    props["volume"] = volume
            except (AttributeError, ValueError, TypeError):
                pass

            if isinstance(r, ct.ConstPressureReactor):
                try:
                    props["energy"] = "on" if r.energy_enabled else "off"
                except Exception:
                    props["energy"] = "on"

            # Mechanism: node-level override first, then infer from thermo
            if isinstance(mech_override, str) and mech_override:
                props["mechanism"] = mech_override
            else:
                guessed = _mechanism_from_thermo(r.thermo)
                if guessed:
                    props["mechanism"] = guessed

        # Optional group propagation (applies to all node types)
        group_name = getattr(r, "group_name", "")
        if isinstance(group_name, str) and group_name:
            props["group"] = group_name

        # Ensure each node has a non-empty unique identifier
        rid = r.name or f"reactor_{id(r)}"

        # Add description from smart comment extraction
        node_dict = {"id": rid, "type": node_type, "properties": props}

        # First try to find description by reactor name
        if rid in object_comments:
            node_dict["description"] = object_comments[rid]
        else:
            # Fallback to old method for backward compatibility
            if metadata and "variable_comments" in metadata:
                var_comments = metadata["variable_comments"]
                for var_name, comment in var_comments.items():
                    if var_name in rid or rid in var_name:
                        node_dict["description"] = comment
                        break

        nodes.append(node_dict)

    # Flow devices (MassFlowController, Valve, PressureController, etc.)
    devices = _unique_flow_devices(set(all_reactors))
    devices_sorted = sorted(
        list(devices), key=lambda d: (_infer_connection_type(d), id(d))
    )
    # Map Python object id -> STONE connection id so PressureController can reference
    # its master MassFlowController by id.
    flow_dev_id_to_cid: Dict[int, str] = {}
    for dev in devices_sorted:
        cid, _, _, _ = _stone_flow_connection_ids(dev)
        flow_dev_id_to_cid[id(dev)] = cid

    connections: List[Dict[str, Any]] = []
    for dev in devices_sorted:
        cid, conn_type, src_id, tgt_id = _stone_flow_connection_ids(dev)

        conn_props: Dict[str, Any] = {}
        if isinstance(dev, ct.MassFlowController):
            # Prefer attribute if available; Cantera exposes mass_flow_rate as a property
            try:
                conn_props["mass_flow_rate"] = float(dev.mass_flow_rate)
            except Exception:
                # Fallbacks: some backends require initialized networks; try alternate attributes
                mdot_attr = getattr(dev, "mdot", None)
                try:
                    mdot_value = mdot_attr() if callable(mdot_attr) else mdot_attr
                except Exception:
                    mdot_value = None
                if isinstance(mdot_value, (int, float)):
                    conn_props["mass_flow_rate"] = float(mdot_value)
                # Else: omit property; conservation will infer it if possible
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
        elif isinstance(dev, ct.PressureController):
            # Cantera often does not expose ``PressureController.primary`` to Python
            # (getter raises NotImplementedError). Infer the master MFC from topology:
            # the primary is the MassFlowController feeding ``dev.upstream``.
            primary_mfc: Optional[ct.MassFlowController] = None
            cand: Any = None
            try:
                cand = dev.primary
            except (NotImplementedError, AttributeError, RuntimeError):
                cand = None
            if isinstance(cand, ct.MassFlowController):
                primary_mfc = cand
            if primary_mfc is None:
                pc_src = dev.upstream
                inlet_mfcs = [
                    d
                    for d in devices_sorted
                    if isinstance(d, ct.MassFlowController) and d.downstream is pc_src
                ]
                if len(inlet_mfcs) == 1:
                    primary_mfc = inlet_mfcs[0]
                elif len(inlet_mfcs) == 0:
                    raise RuntimeError(
                        f"PressureController '{cid}': no MassFlowController found "
                        f"feeding upstream reactor '{getattr(pc_src, 'name', id(pc_src))}'."
                    )
                else:
                    raise RuntimeError(
                        f"PressureController '{cid}': multiple MassFlowControllers "
                        f"feed the upstream reactor; name the intended master MFC in "
                        f"Python or use a single inlet MFC per reactor for sim2stone."
                    )
            master_cid = flow_dev_id_to_cid[id(primary_mfc)]
            conn_props["master"] = master_cid
            try:
                conn_props["pressure_coeff"] = float(dev.pressure_coeff)
            except Exception:
                conn_props["pressure_coeff"] = 0.0

        # Create connection dictionary
        conn_dict = {
            "id": cid,
            "type": conn_type,
            "properties": conn_props,
            "source": src_id,
            "target": tgt_id,
        }

        # Add description from smart comment extraction if available
        if cid in object_comments:
            conn_dict["description"] = object_comments[cid]

        connections.append(conn_dict)

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

        # Create wall connection dictionary
        wall_dict = {
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

        # Add description from smart comment extraction if available
        if cid in object_comments:
            wall_dict["description"] = object_comments[cid]

        connections.append(wall_dict)

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
    """Convert a Cantera ReactorNet to a STONE v2 YAML string.

    Emits STONE v2 format with a top-level ``network:`` key containing all
    nodes and connections as typed items. Each node is ``{id, KindName: {props}}``
    and each connection is ``{id, KindName: {props}, source, target}``.
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

    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    stone_cm = CommentedMap()

    # metadata (if available)
    if "metadata" in internal:
        metadata_cm = CommentedMap()
        for key, value in internal["metadata"].items():
            if key == "description" and isinstance(value, str) and "\n" in value:
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

    # network: list of node and connection items in STONE v2 format
    network_seq = CommentedSeq()

    for node in internal.get("nodes", []):
        node_cm = CommentedMap()
        node_cm["id"] = node["id"]
        # Copy properties to avoid mutating internal
        props = dict(node.get("properties", {}) or {})
        # Extract per-node mechanism; emit at node level (not inside kind block)
        node_mech = props.pop("mechanism", None)
        if node_mech == mechanism:
            node_mech = None
        # Remove group from props — group assignment is inferred in v2
        props.pop("group", None)
        # Reservoir state fields are valid in v2; other reactor state is in initial:
        # Keep temperature/pressure/composition for Reservoir nodes only.
        node_type = node.get("type", "")
        if node_type not in ("Reservoir", "OutletSink"):
            # Move state to initial: block for non-boundary nodes
            initial: Dict[str, Any] = {}
            for state_key in ("temperature", "pressure", "composition"):
                if state_key in props:
                    initial[state_key] = props.pop(state_key)
            if initial:
                props["initial"] = initial
        # Emit null (bare key) when props are empty
        node_cm[node_type] = props if props else None
        if node_mech is not None:
            node_cm["mechanism"] = node_mech
        if "description" in node:
            desc = node["description"]
            if isinstance(desc, str) and "\n" in desc:
                from ruamel.yaml.scalarstring import LiteralScalarString

                node_cm["description"] = LiteralScalarString(desc)
            else:
                node_cm["description"] = desc
        network_seq.append(node_cm)

    for conn in internal.get("connections", []):
        conn_cm = CommentedMap()
        conn_cm["id"] = conn["id"]
        conn_props = dict(conn.get("properties", {}) or {})
        conn_cm[conn["type"]] = conn_props if conn_props else None
        conn_cm["source"] = conn["source"]
        conn_cm["target"] = conn["target"]
        if "description" in conn:
            desc = conn["description"]
            if isinstance(desc, str) and "\n" in desc:
                from ruamel.yaml.scalarstring import LiteralScalarString

                conn_cm["description"] = LiteralScalarString(desc)
            else:
                conn_cm["description"] = desc
        network_seq.append(conn_cm)

    stone_cm["network"] = network_seq
    try:
        stone_cm.yaml_set_comment_before_after_key("network", before="\n")
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
    """Serialize a Cantera ReactorNet to a STONE YAML file.

    Examples
    --------
    .. minigallery:: boulder.sim2stone.write_sim_as_yaml
       :add-heading: Examples using write_sim_as_yaml
    """
    yaml_str = sim_to_stone_yaml(
        sim,
        default_mechanism=default_mechanism,
        source_file=source_file,
        include_comments=include_comments,
    )
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)
