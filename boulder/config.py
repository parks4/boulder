"""Configuration management for the Boulder application.

Supports YAML format with 🪨 STONE standard - an elegant configuration format
where component types are keys containing their properties.

STONE v2 is the current authored format. Files using top-level ``network:``
(single stage) or ``stages:`` + dynamic stage blocks (multi-stage) are v2.
Historic STONE v1 files using top-level ``nodes:`` / ``connections:`` /
``groups:`` are rejected. See STONE_SPECIFICATIONS.md.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

import yaml
from ruamel.yaml import YAML

# Global variable for temperature scale coloring
USE_TEMPERATURE_SCALE = True

# Global variable to control which converter to use
# Unified converter architecture - no longer needed
# USE_DUAL_CONVERTER = True

# Global variable for the Cantera mechanism to use consistently across the application
CANTERA_MECHANISM = "gri30.yaml"

# Theme setting: "light", "dark", or "system"
THEME = "system"


# Locked STONE top-level vocabulary.  Any other top-level key is rejected
# by :func:`normalize_config` — this is the single source of truth for
# allowed sections, consumed by the CLI's ``boulder validate`` command and
# by the UI's config linter.
STONE_TOP_LEVEL_KEYS: frozenset = frozenset(
    {
        "metadata",
        "phases",
        "settings",
        "nodes",
        "connections",
        "groups",
        "output",
        "export",
        "sweeps",
        "scenarios",
    }
)

# Allowed top-level keys in a STONE v2 file (before dynamic stage blocks are
# added).  Dynamic stage block names (declared under ``stages:``) are also
# permitted; they are validated separately by :func:`_normalize_v2`.
STONE_V2_BASE_KEYS: frozenset = frozenset(
    {
        "metadata",
        "phases",
        "settings",
        "stages",
        "network",
        "output",
        "export",
        "sweeps",
        "scenarios",
    }
)

# Names that may not be used as stage ids.
STONE_V2_RESERVED_STAGE_NAMES: frozenset = frozenset(
    {
        "metadata",
        "phases",
        "settings",
        "stages",
        "network",
        "nodes",
        "connections",
    }
)

# Keys that are valid on a connection item (in addition to the kind key).
_CONN_STANDARD_FIELDS: frozenset = frozenset(
    {
        "id",
        "source",
        "target",
        "metadata",
        "mechanism_switch",
        "mass_flow_rate",
        "logical",
        "description",
        "label",
    }
)

# Keys that are valid on a node item (in addition to the kind key).
_NODE_STANDARD_FIELDS: frozenset = frozenset(
    {
        "id",
        "metadata",
        "mechanism",
        "description",
        "label",
    }
)

# Known Cantera flow-device kinds.
_FLOW_DEVICE_KINDS: frozenset = frozenset(
    {"MassFlowController", "Valve", "PressureController", "Wall"}
)

# Reactor kinds that forbid a top-level ``temperature:`` field (all const-volume
# kinds). Since the kind registry is open-ended, we check the inverse: only
# kinds that explicitly model an isothermal/fixed-T option may carry it.
_ISOTHERMAL_KINDS: frozenset = frozenset(
    {"IdealGasConstPressureReactor", "ConstPressureReactor"}
)

# Const-pressure kinds that allow a top-level ``pressure:`` as an operating
# constraint.
_CONST_PRESSURE_KINDS: frozenset = frozenset(
    {
        "IdealGasConstPressureReactor",
        "ConstPressureReactor",
        "DesignPSR",
        "DesignTorchInstantaneousHeating",
        "DesignPFR",
        "DesignPFRThinShell",
        "DesignTubeFurnace",
    }
)


# ---------------------------------------------------------------------------
# STONE v2 — dialect detection and normalization
# ---------------------------------------------------------------------------


def _detect_stone_dialect(raw: Dict[str, Any]) -> str:
    """Detect STONE dialect from raw YAML dict.

    Returns
    -------
    str
        One of ``'v2_network'``, ``'v2_staged'``, ``'internal'``.
        ``'internal'`` means the dict is already in the internal normalized
        format (produced by a previous call to :func:`normalize_config` or
        constructed directly by tests/plugins).

    Raises
    ------
    ValueError
        For STONE v1 files (actionable error) or completely unknown shapes.
    """
    has_nodes = "nodes" in raw
    has_connections = "connections" in raw
    has_groups = "groups" in raw
    has_stages = "stages" in raw
    has_network = "network" in raw

    # Internal format: has nodes + (already has type/properties on first node).
    # This happens when tests or plugins pass a pre-normalized dict directly.
    if has_nodes and not has_stages and not has_network:
        nodes = raw.get("nodes") or []
        if nodes and isinstance(nodes[0], dict) and "type" in nodes[0]:
            return "internal"
        # Has nodes but first node doesn't have `type` → v1 YAML shape.
        raise ValueError(
            "STONE v1 format detected (top-level 'nodes:', 'connections:', or 'groups:'). "
            "Migrate to STONE v2. See STONE_SPECIFICATIONS.md."
        )

    if has_groups and not has_nodes and not has_stages and not has_network:
        # Could be internal format with groups only (empty network). Treat as internal.
        return "internal"

    if has_connections and not has_nodes and not has_stages and not has_network:
        raise ValueError(
            "STONE v1 format detected (top-level 'connections:' without 'network:' or 'stages:'). "
            "Migrate to STONE v2. See STONE_SPECIFICATIONS.md."
        )

    if has_stages and has_network:
        raise ValueError(
            "STONE v2 format error: 'stages:' and 'network:' are mutually exclusive. "
            "Use 'network:' for a single-stage network or 'stages:' for a multi-stage network. "
            "See STONE_SPECIFICATIONS.md."
        )

    if has_stages:
        return "v2_staged"

    if has_network:
        return "v2_network"

    raise ValueError(
        "Cannot detect STONE dialect: no 'network:', 'stages:', or 'nodes:' found. "
        "Use 'network:' (single stage) or 'stages:' + stage blocks (multi-stage). "
        "See STONE_SPECIFICATIONS.md."
    )


def _classify_item(item: Dict[str, Any], stage_id: str) -> str:
    """Return ``'node'`` or ``'connection'`` for a STONE v2 stage item.

    Raises
    ------
    ValueError
        When the item is ambiguous or malformed.
    """
    item_id = item.get("id", "<unnamed>")
    has_source = "source" in item
    has_target = "target" in item

    if has_source and not has_target:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': item '{item_id}' has 'source:' but "
            "no 'target:'. Both 'source:' and 'target:' are required for connections. "
            "See STONE_SPECIFICATIONS.md."
        )

    if has_target and not has_source:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': item '{item_id}' has 'target:' but "
            "no 'source:'. Both 'source:' and 'target:' are required for connections. "
            "See STONE_SPECIFICATIONS.md."
        )

    return "connection" if (has_source and has_target) else "node"


def _extract_kind(
    item: Dict[str, Any],
    item_type: str,
    stage_id: str,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Extract the kind key and its properties from a stage item.

    Returns
    -------
    (kind_name, kind_props)
        ``kind_name`` is ``None`` for a logical connection (no kind key).
    """
    item_id = item.get("id", "<unnamed>")
    standard = (
        _CONN_STANDARD_FIELDS if item_type == "connection" else _NODE_STANDARD_FIELDS
    )
    kind_keys = [k for k in item if k not in standard and k != "id"]

    if len(kind_keys) > 1:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': item '{item_id}' has multiple "
            f"kind keys {kind_keys}. An item may declare exactly one kind. "
            "See STONE_SPECIFICATIONS.md."
        )

    if kind_keys:
        kind = kind_keys[0]
        raw_props = item[kind]
        if raw_props is None:
            props: Dict[str, Any] = {}
        elif isinstance(raw_props, dict):
            props = raw_props
        else:
            raise ValueError(
                f"STONE v2 error in stage '{stage_id}': item '{item_id}' kind "
                f"'{kind}' value must be a mapping or null, got {type(raw_props).__name__}."
            )
        return kind, props

    # No kind key → logical connection (permitted only for inter-stage connections)
    if item_type == "node":
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': item '{item_id}' has no node "
            "kind key (e.g. 'IdealGasReactor', 'Reservoir'). "
            "See STONE_SPECIFICATIONS.md."
        )

    return None, {}


def _validate_node_state_placement(
    node_id: str,
    kind: str,
    props: Dict[str, Any],
    stage_id: str,
) -> None:
    """Raise ValueError when a reactor has forbidden top-level state fields."""
    if kind in ("Reservoir", "OutletSink"):
        return

    if "inlet" in props or "outlet" in props:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': node '{node_id}' uses inline "
            "'inlet:' or 'outlet:' port syntax which is not valid in STONE v2. "
            "Author the edge as an explicit connection item in the same block. "
            "See STONE_SPECIFICATIONS.md."
        )

    if "composition" in props or "mass_composition" in props:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': reactor '{node_id}' declares "
            "top-level 'composition:' or 'mass_composition:'. Reactor operating "
            "composition is inferred from upstream inlets. Use 'initial:' for a "
            "seeding guess. See STONE_SPECIFICATIONS.md."
        )

    if "temperature" in props and kind not in _ISOTHERMAL_KINDS:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': reactor '{node_id}' declares "
            "top-level 'temperature:' which is invalid for const-volume reactor kinds. "
            "Use 'initial:' for a seeding guess. See STONE_SPECIFICATIONS.md."
        )

    initial = props.get("initial") or {}
    if "composition" in initial and "mass_composition" in initial:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': reactor '{node_id}' initial: "
            "block has both 'composition:' and 'mass_composition:'. They are mutually "
            "exclusive. See STONE_SPECIFICATIONS.md."
        )

    known_sizing_keys = {"volume", "t_res_s"}
    sizing = [k for k in props if k in known_sizing_keys]
    if len(sizing) > 1:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': reactor '{node_id}' is "
            f"over-specified: {sizing}. Use one sizing basis per reactor. "
            "See STONE_SPECIFICATIONS.md."
        )


def _validate_reservoir(node_id: str, props: Dict[str, Any], stage_id: str) -> None:
    """Raise ValueError when a Reservoir is missing required state."""
    if "composition" not in props and "mass_composition" not in props:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': Reservoir '{node_id}' is missing "
            "'composition:' (required boundary state). See STONE_SPECIFICATIONS.md."
        )
    if "temperature" not in props:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': Reservoir '{node_id}' is missing "
            "'temperature:' (required boundary state). See STONE_SPECIFICATIONS.md."
        )
    if "composition" in props and "mass_composition" in props:
        raise ValueError(
            f"STONE v2 error in stage '{stage_id}': Reservoir '{node_id}' has both "
            "'composition:' and 'mass_composition:'. They are mutually exclusive. "
            "See STONE_SPECIFICATIONS.md."
        )


def _build_stage_graph(
    stage_ids: List[str],
    items_by_stage: Dict[str, List[Dict[str, Any]]],
    node_to_stage: Dict[str, str],
) -> Dict[str, List[str]]:
    """Build stage DAG: {stage_id: [upstream stage ids]}.

    A logical inter-stage connection in stage S declares source from a node in
    stage U → S depends on U.
    """
    deps: Dict[str, List[str]] = {s: [] for s in stage_ids}
    for stage_id in stage_ids:
        for item in items_by_stage.get(stage_id, []):
            kind_type = _classify_item(item, stage_id)
            if kind_type != "connection":
                continue
            source_id = item.get("source", "")
            source_stage = node_to_stage.get(source_id)
            if source_stage and source_stage != stage_id:
                deps[stage_id].append(source_stage)
    return deps


def _topological_sort(stage_ids: List[str], deps: Dict[str, List[str]]) -> List[str]:
    """Kahn's algorithm topological sort. Raises ValueError on cycle."""
    in_degree: Dict[str, int] = {s: 0 for s in stage_ids}
    adj: Dict[str, List[str]] = {s: [] for s in stage_ids}
    for stage, upstream_list in deps.items():
        for upstream in upstream_list:
            adj[upstream].append(stage)
            in_degree[stage] += 1

    queue = [s for s in stage_ids if in_degree[s] == 0]
    result: List[str] = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for nxt in adj[node]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(result) != len(stage_ids):
        remaining = [s for s in stage_ids if s not in result]
        raise ValueError(
            f"STONE v2 error: stage dependency cycle detected among stages {remaining}. "
            "Inter-stage edges must form a DAG. See STONE_SPECIFICATIONS.md."
        )
    return result


def _normalize_v2(raw: Dict[str, Any], dialect: str) -> Dict[str, Any]:
    """Convert a STONE v2 dict into the internal normalized format.

    The internal format uses flat ``nodes``, ``connections``, and ``groups``
    sections as consumed by the rest of the Boulder pipeline (staged solver,
    converter, validation). All STONE v2 structural rules are enforced here.

    Parameters
    ----------
    raw:
        Raw dict loaded from a STONE v2 YAML file.
    dialect:
        ``'v2_network'`` or ``'v2_staged'``.

    Returns
    -------
    dict
        Internal-format config ready for :func:`normalize_config`'s existing
        pipeline (unit coercion, port shortcuts — now rejected — and group
        synthesis).
    """
    if dialect == "v2_network":
        return _normalize_v2_network(raw)
    return _normalize_v2_staged(raw)


def _normalize_v2_network(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a single-stage ``network:`` STONE v2 file."""
    unknown = sorted(set(raw.keys()) - STONE_V2_BASE_KEYS)
    if unknown:
        raise ValueError(
            f"STONE v2 error: unknown top-level keys {unknown}. "
            f"Allowed keys for a single-stage 'network:' file: "
            f"{sorted(STONE_V2_BASE_KEYS)}. "
            "See STONE_SPECIFICATIONS.md."
        )

    network_items = raw.get("network") or []
    if not isinstance(network_items, list):
        raise ValueError("STONE v2 error: 'network:' must be a list of items.")

    # Resolve global mechanism for the default stage
    phases = raw.get("phases") or {}
    default_mech = "gri30.yaml"
    if isinstance(phases, dict):
        gas_phase = phases.get("gas") or {}
        if isinstance(gas_phase, dict):
            default_mech = gas_phase.get("mechanism") or default_mech

    nodes, connections = _process_stage_items(
        network_items, "network", intra_stage=True
    )

    # Build internal format
    result = {k: raw[k] for k in ("metadata", "phases", "settings") if k in raw}
    for k in ("output", "export", "sweeps", "scenarios"):
        if k in raw:
            result[k] = raw[k]

    result["nodes"] = nodes
    result["connections"] = connections
    result["groups"] = {
        "default": {
            "stage_order": 1,
            "mechanism": default_mech,
            "solve": "advance_to_steady_state",
        }
    }
    for n in result["nodes"]:
        n["group"] = "default"
    for c in result["connections"]:
        c["group"] = "default"
    return result


def _normalize_v2_staged(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a multi-stage ``stages:`` STONE v2 file."""
    stages_meta = raw.get("stages") or {}
    if not isinstance(stages_meta, dict):
        raise ValueError(
            "STONE v2 error: 'stages:' must be a mapping of stage metadata."
        )

    stage_ids = list(stages_meta.keys())

    # Check reserved stage names
    for sid in stage_ids:
        if sid in STONE_V2_RESERVED_STAGE_NAMES:
            raise ValueError(
                f"STONE v2 error: stage id '{sid}' is a reserved name. "
                f"Reserved names: {sorted(STONE_V2_RESERVED_STAGE_NAMES)}. "
                "See STONE_SPECIFICATIONS.md."
            )

    # Determine which top-level keys are expected: base keys + stage block names
    allowed_top = STONE_V2_BASE_KEYS | set(stage_ids)
    unknown = sorted(set(raw.keys()) - allowed_top)
    if unknown:
        raise ValueError(
            f"STONE v2 error: unknown top-level keys {unknown}. "
            "Each top-level block must either be a known section key or a stage "
            "declared under 'stages:'. See STONE_SPECIFICATIONS.md."
        )

    # Bijection: every stage in stages: must have a block; every block must be in stages:
    for sid in stage_ids:
        if sid not in raw:
            raise ValueError(
                f"STONE v2 error: stage '{sid}' is declared in 'stages:' but has no "
                f"matching top-level block '{sid}:'. See STONE_SPECIFICATIONS.md."
            )
    for key in raw:
        if key in STONE_V2_BASE_KEYS:
            continue
        if key not in stages_meta:
            raise ValueError(
                f"STONE v2 error: top-level block '{key}' has no matching entry in "
                "'stages:'. Declare it under 'stages:' or remove the block. "
                "See STONE_SPECIFICATIONS.md."
            )

    # Validate stage metadata (solve, advance_time)
    for sid, smeta in stages_meta.items():
        if not isinstance(smeta, dict):
            raise ValueError(
                f"STONE v2 error: stage '{sid}' metadata must be a mapping."
            )
        solve = smeta.get("solve")
        if solve not in ("advance", "advance_to_steady_state"):
            raise ValueError(
                f"STONE v2 error: stage '{sid}' has invalid 'solve:' value '{solve}'. "
                "Allowed values: 'advance', 'advance_to_steady_state'. "
                "See STONE_SPECIFICATIONS.md."
            )
        has_at = "advance_time" in smeta
        if solve == "advance" and not has_at:
            raise ValueError(
                f"STONE v2 error: stage '{sid}' uses solve: advance but is missing "
                "'advance_time:'. See STONE_SPECIFICATIONS.md."
            )
        if solve == "advance_to_steady_state" and has_at:
            raise ValueError(
                f"STONE v2 error: stage '{sid}' uses solve: advance_to_steady_state "
                "but declares 'advance_time:' which is forbidden for this mode. "
                "See STONE_SPECIFICATIONS.md."
            )

    # Process items for each stage to get node/connection lists
    items_by_stage: Dict[str, List[Dict[str, Any]]] = {}
    all_nodes: List[Dict[str, Any]] = []
    all_connections: List[Dict[str, Any]] = []
    node_to_stage: Dict[str, str] = {}  # node_id → stage_id

    for sid in stage_ids:
        stage_items = raw.get(sid) or []
        if not isinstance(stage_items, list):
            raise ValueError(
                f"STONE v2 error: stage block '{sid}' must be a list of items, "
                f"got {type(stage_items).__name__}."
            )
        items_by_stage[sid] = stage_items
        # First pass: collect node ids to build node_to_stage mapping
        for item in stage_items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id and "source" not in item and "target" not in item:
                node_to_stage[item_id] = sid

    # Second pass: duplicate id check across stages
    seen_ids: Dict[str, str] = {}
    for sid in stage_ids:
        for item in items_by_stage.get(sid, []):
            if not isinstance(item, dict):
                continue
            iid = item.get("id")
            if not iid:
                continue
            if iid in seen_ids:
                raise ValueError(
                    f"STONE v2 error: id '{iid}' appears in both stage '{seen_ids[iid]}' "
                    f"and stage '{sid}'. Node ids must be globally unique. "
                    "See STONE_SPECIFICATIONS.md."
                )
            seen_ids[iid] = sid

    # Build the stage DAG and determine execution order
    deps = _build_stage_graph(stage_ids, items_by_stage, node_to_stage)
    ordered_stages = _topological_sort(stage_ids, deps)

    # Now process stage items with intra-stage logical connection detection
    for sid in stage_ids:
        stage_nodes, stage_conns = _process_stage_items(
            items_by_stage.get(sid, []),
            sid,
            intra_stage=False,
            node_to_stage=node_to_stage,
        )
        for n in stage_nodes:
            n["group"] = sid
        for c in stage_conns:
            c["group"] = sid
        all_nodes.extend(stage_nodes)
        all_connections.extend(stage_conns)

    # Build groups section from stage metadata (topological order)
    groups: Dict[str, Any] = {}
    for order_idx, sid in enumerate(ordered_stages):
        smeta = stages_meta[sid]
        group_entry: Dict[str, Any] = {
            "stage_order": order_idx + 1,
            "mechanism": smeta.get("mechanism", "gri30.yaml"),
            "solve": smeta["solve"],
        }
        if "advance_time" in smeta:
            group_entry["advance_time"] = smeta["advance_time"]
        groups[sid] = group_entry

    result = {k: raw[k] for k in ("metadata", "phases", "settings") if k in raw}
    for k in ("output", "export", "sweeps", "scenarios"):
        if k in raw:
            result[k] = raw[k]

    result["nodes"] = all_nodes
    result["connections"] = all_connections
    result["groups"] = groups
    return result


def _process_stage_items(
    items: List[Any],
    stage_id: str,
    intra_stage: bool,
    node_to_stage: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse a list of STONE v2 stage items into (nodes, connections).

    Parameters
    ----------
    items:
        List of raw item dicts from a stage block.
    stage_id:
        Stage name (used for error messages).
    intra_stage:
        ``True`` for ``network:`` (single stage) — logical connections are invalid.
    node_to_stage:
        Mapping of node_id → stage_id for detecting inter/intra-stage edges.
    """
    nodes: List[Dict[str, Any]] = []
    connections: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            raise ValueError(
                f"STONE v2 error in stage '{stage_id}': each item must be a mapping."
            )
        item_id = item.get("id")
        if not item_id:
            raise ValueError(
                f"STONE v2 error in stage '{stage_id}': every item must have an 'id:' field."
            )

        item_type = _classify_item(item, stage_id)
        kind, kind_props = _extract_kind(item, item_type, stage_id)

        if item_type == "node":
            # Validate OutletSink separately (no required state)
            if kind == "OutletSink":
                node: Dict[str, Any] = {
                    "id": item_id,
                    "type": "OutletSink",
                    "properties": kind_props,
                }
                for fld in ("metadata", "description", "label", "mechanism"):
                    if fld in item:
                        node[fld] = item[fld]
                nodes.append(node)
                continue

            if kind == "Reservoir":
                _validate_reservoir(item_id, kind_props, stage_id)
            else:
                _validate_node_state_placement(item_id, kind, kind_props, stage_id)

            node = {
                "id": item_id,
                "type": kind,
                "properties": kind_props,
            }
            for fld in ("metadata", "description", "label"):
                if fld in item:
                    node[fld] = item[fld]
            if "mechanism" in item:
                node["mechanism"] = item["mechanism"]
            nodes.append(node)

        else:
            # Connection
            source = item["source"]
            target = item["target"]

            if kind is None:
                # Logical connection — only valid inter-stage
                if intra_stage:
                    raise ValueError(
                        f"STONE v2 error in stage '{stage_id}': item '{item_id}' is a "
                        "logical connection (no kind key) inside a single-stage 'network:'. "
                        "Logical connections are only valid between stages. "
                        "See STONE_SPECIFICATIONS.md."
                    )
                if node_to_stage is not None:
                    src_stage = node_to_stage.get(source)
                    tgt_stage = node_to_stage.get(target)
                    if (
                        src_stage is not None
                        and tgt_stage is not None
                        and src_stage == tgt_stage
                    ):
                        raise ValueError(
                            f"STONE v2 error in stage '{stage_id}': logical connection "
                            f"'{item_id}' connects '{source}' and '{target}' which are in "
                            f"the same stage '{src_stage}'. Logical connections must be "
                            "inter-stage. See STONE_SPECIFICATIONS.md."
                        )
                conn_props: Dict[str, Any] = {}
                if "mass_flow_rate" in item:
                    conn_props["mass_flow_rate"] = item["mass_flow_rate"]
                conn: Dict[str, Any] = {
                    "id": item_id,
                    "type": "MassFlowController",
                    "source": source,
                    "target": target,
                    "properties": conn_props,
                    "logical": True,
                }
                if "mechanism_switch" in item:
                    conn["mechanism_switch"] = item["mechanism_switch"]
                if "metadata" in item:
                    conn["metadata"] = item["metadata"]
                connections.append(conn)
            else:
                # OutletSink cannot be a source
                if node_to_stage is not None:
                    pass  # OutletSink check happens at validation time

                conn_props = dict(kind_props)
                conn = {
                    "id": item_id,
                    "type": kind,
                    "source": source,
                    "target": target,
                    "properties": conn_props,
                }
                if "mechanism_switch" in item:
                    conn["mechanism_switch"] = item["mechanism_switch"]
                if "metadata" in item:
                    conn["metadata"] = item["metadata"]
                if "mass_flow_rate" in item and "mass_flow_rate" not in conn_props:
                    conn_props["mass_flow_rate"] = item["mass_flow_rate"]
                connections.append(conn)

    return nodes, connections


def get_yaml_with_comments():
    """Get a ruamel.yaml YAML object configured to preserve comments."""
    yaml_obj = YAML()
    yaml_obj.preserve_quotes = True
    yaml_obj.width = 4096  # Prevent line wrapping
    # Configure indentation to match pretty-format-yaml expectations
    # mapping=2: 2 spaces for dictionary keys
    # sequence=2: 2 spaces for list items after the dash
    # offset=0: no extra indentation for the dash itself
    yaml_obj.indent(mapping=2, sequence=2, offset=0)
    return yaml_obj


def load_config_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file with 🪨 STONE standard."""
    _, ext = os.path.splitext(config_path.lower())

    if ext not in [".yaml", ".yml"]:
        raise ValueError(
            f"Only YAML format with 🪨 STONE standard (.yaml/.yml) files are supported. "
            f"Got: {ext}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config_file_with_comments(config_path: str):
    """Load configuration from YAML file preserving comments with 🪨 STONE standard."""
    _, ext = os.path.splitext(config_path.lower())

    if ext not in [".yaml", ".yml"]:
        raise ValueError(
            f"Only YAML format with 🪨 STONE standard (.yaml/.yml) files are supported. "
            f"Got: {ext}"
        )

    yaml_obj = get_yaml_with_comments()
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml_obj.load(f)


def expand_composite_kinds(config: Dict[str, Any], plugins: Any) -> None:
    """Append satellite nodes/connections produced by reactor-kind unfolders.

    For each node whose ``type`` has a registered
    :data:`~boulder.cantera_converter.ReactorUnfolder`, invoke the unfolder and
    append the returned nodes/connections into *config* in place.

    Generated ids must be unique: if the unfolder emits an id that already
    exists and the existing entry is **not** byte-identical, a ``ValueError``
    is raised.  Silent overrides are forbidden so that composite reactors
    compose cleanly with each other and with explicit user-declared nodes.

    This function runs **after** :func:`expand_port_shortcuts` so any
    user-declared ``inlet:``/``outlet:`` ports have already been converted
    into explicit connections before unfolders read the node.

    Parameters
    ----------
    config :
        Normalized config dict, mutated in place.
    plugins :
        :class:`~boulder.cantera_converter.BoulderPlugins` whose
        ``reactor_unfolders`` dict is consulted.
    """
    nodes = config.get("nodes") or []
    conns = config.setdefault("connections", [])
    by_node_id: Dict[str, Any] = {n["id"]: n for n in nodes if "id" in n}
    by_conn_id: Dict[str, Any] = {c["id"]: c for c in conns if "id" in c}
    for node in list(nodes):  # snapshot — we may append to nodes below
        unfolder = plugins.reactor_unfolders.get(node.get("type"))
        if unfolder is None:
            continue
        result = unfolder(node) or {}
        for n in result.get("nodes", []):
            existing = by_node_id.get(n["id"])
            if existing is None:
                nodes.append(n)
                by_node_id[n["id"]] = n
            elif existing != n:
                raise ValueError(
                    f"Composite unfold collision: node id '{n['id']}' "
                    f"emitted by unfolder for '{node['id']}' conflicts "
                    "with an existing node. Rename one of them."
                )
        for c in result.get("connections", []):
            existing = by_conn_id.get(c["id"])
            if existing is None:
                conns.append(c)
                by_conn_id[c["id"]] = c
            elif existing != c:
                raise ValueError(
                    f"Composite unfold collision: connection id '{c['id']}' "
                    f"emitted by unfolder for '{node['id']}' conflicts "
                    "with an existing connection."
                )


def normalize_config(config: Dict[str, Any], plugins: Any = None) -> Dict[str, Any]:
    """Normalize configuration from YAML with 🪨 STONE standard to internal format.

    Accepts STONE v2 (``network:`` or ``stages:`` dialect) and converts to the
    internal flat format (``nodes``, ``connections``, ``groups``) consumed by the
    rest of the Boulder pipeline.

    Historic STONE v1 files (``nodes:``, ``connections:``, ``groups:``) are
    rejected with an actionable error message.

    Internal format::

        nodes:
          - id: reactor1
            type: IdealGasReactor
            properties:
                temperature: 1000
    """
    from .utils import coerce_config_units  # noqa: PLC0415

    if plugins is None:
        from .cantera_converter import get_plugins  # noqa: PLC0415

        plugins = get_plugins()

    # --- STONE v2 detection and normalization ---
    # Detect dialect first; this raises ValueError for v1 or unknown shapes.
    dialect = _detect_stone_dialect(config)
    if dialect == "internal":
        # Already in internal format (passed by tests/plugins); skip v2 normalization.
        normalized = config.copy()
    else:
        # Convert v2 to internal flat format (nodes/connections/groups).
        normalized = _normalize_v2(config, dialect)

    # Convert unit-bearing strings ("25 degC", "1.3 bar", "470 kg/d", …) to
    # canonical SI floats before any further processing.  Plain numeric values
    # are left untouched so existing YAML configs that already store SI values
    # remain fully backward-compatible.
    coerce_config_units(normalized)

    # At this point `normalized` has the internal flat shape with `nodes`,
    # `connections`, and `groups` (produced by _normalize_v2). The type/
    # properties extraction already happened in _process_stage_items, so the
    # loops below are no-ops for v2 but are kept to remain compatible with
    # any internal callers that pass an already-internal dict directly.

    # Normalize nodes — ensure every node has type/properties keys.
    if "nodes" in normalized:
        for node in normalized["nodes"]:
            if "type" not in node:
                standard_fields = {"id", "metadata", "mechanism", "group", "logical"}
                type_keys = [k for k in node.keys() if k not in standard_fields]

                if type_keys:
                    type_name = type_keys[0]
                    properties = node[type_name]

                    del node[type_name]
                    node["type"] = type_name
                    node["properties"] = (
                        properties if isinstance(properties, dict) else {}
                    )
            # If a node-level mechanism is present, move it into properties for internal use
            if "mechanism" in node:
                props = node.setdefault("properties", {})
                if "mechanism" not in props:
                    props["mechanism"] = node["mechanism"]

    # Normalize connections — ensure every connection has type/properties keys.
    if "connections" in normalized:
        for connection in normalized["connections"]:
            if "type" not in connection:
                standard_fields = {
                    "id",
                    "source",
                    "target",
                    "metadata",
                    "mechanism_switch",
                    "group",
                    "logical",
                }
                type_keys = [k for k in connection.keys() if k not in standard_fields]

                if type_keys:
                    type_name = type_keys[0]
                    properties = connection[type_name]

                    del connection[type_name]
                    connection["type"] = type_name
                    connection["properties"] = (
                        properties if isinstance(properties, dict) else {}
                    )
                    # mechanism_switch is preserved at the connection top-level

    # Expand node-level `inlet:` / `outlet:` ports into regular `connections:`
    # entries so downstream code (converter, staged solver, visualisation) sees
    # the canonical shape.  Must run AFTER the node/connection normalisation
    # loops above because it reads node.properties and writes to connections.
    expand_port_shortcuts(normalized)

    # Expand composite reactor kinds into their satellite nodes/connections.
    # Runs after port shortcuts so user-declared inlet/outlet ports have already
    # become real connections before unfolders read the node.
    expand_composite_kinds(normalized, plugins)

    # Propagate process pressure from terminal boundary nodes (e.g. OutletSink)
    # to flow-connected upstream nodes that lack an explicit pressure.  Wall
    # edges are excluded so ambient/satellite Reservoirs keep their own pressure.
    propagate_terminal_pressure_defaults(normalized)

    # Topologically order connections so every PressureController is built
    # after the MassFlowController it points at via `master:`.  This is a
    # Cantera requirement (the primary device must exist first).
    _sort_connections_by_master(normalized)

    # Pass through the groups section unchanged (used by staged solver)
    # No normalization needed: groups is a plain dict {group_id: {stage_order, mechanism, solve}}

    # Synthesize a single "default" stage when the YAML does not declare any
    # groups.  Every simulation runs through the staged solver
    # ({build_stage_graph, solve_staged}) with one ordered stage.  Previously,
    # ungrouped nodes were silently dropped by build_stage_graph; tagging them
    # with group="default" here keeps them in the network.
    synthesize_default_group(normalized)

    return normalized


def expand_port_shortcuts(config: Dict[str, Any]) -> None:
    """Expand node-level ``inlet:`` / ``outlet:`` ports into ``connections:``.

    STONE YAMLs may declare flow ports inline on a reactor node to cut the
    boilerplate of single-inlet, single-outlet pipelines::

        nodes:
          - id: tube_furnace
            DesignTubeFurnace:
              inlet:  {from: feed, mass_flow_rate: 3.33e-4}
              outlet: {to: outlet}     # default device: PressureController(K=0)

    This helper rewrites those ports into explicit, normalised connection
    entries (equivalent to what a user would have written by hand).  Default
    conventions:

    * ``inlet`` → ``MassFlowController`` with id ``f"{from}_to_{nid}"``.  An
      omitted ``mass_flow_rate`` means "let global conservation resolve it".
    * ``outlet`` → ``PressureController`` with ``pressure_coeff=0.0`` and
      ``master`` auto-picked as the unique inlet MFC of the node.  Multi-inlet
      reactors must either set ``master:`` explicitly or switch to
      ``device: MassFlowController``.

    Conflicts (duplicate id, same ``(source, target)`` pair as an explicit
    connection) raise ``ValueError`` so silent overrides are impossible.
    """
    nodes = config.get("nodes") or []
    connections = config.setdefault("connections", [])
    if not isinstance(connections, list):
        return

    explicit_conn_ids = {c.get("id") for c in connections if c.get("id")}
    explicit_edges = {(c.get("source"), c.get("target")) for c in connections}
    mfc_inlets_by_target: Dict[str, list] = {}
    for conn in connections:
        if conn.get("type") == "MassFlowController":
            tgt = conn.get("target")
            if tgt:
                mfc_inlets_by_target.setdefault(tgt, []).append(conn.get("id"))

    synthesized: list = []

    def _node_group(node: Dict[str, Any]) -> Optional[str]:
        props = node.get("properties") or {}
        return node.get("group") or props.get("group")

    # Pass 1: inlet ports first so outlet master-picking sees them.
    for node in nodes:
        props = node.get("properties")
        if not isinstance(props, dict):
            continue
        inlet = props.pop("inlet", None)
        if inlet is None:
            continue
        if not isinstance(inlet, dict):
            raise ValueError(
                f"Node '{node.get('id')}' 'inlet' port must be a mapping, "
                f"got {type(inlet).__name__}."
            )
        nid = node["id"]
        from_id = inlet.get("from")
        if not from_id:
            raise ValueError(
                f"Node '{nid}' inlet port is missing required 'from:' field."
            )
        cid = f"{from_id}_to_{nid}"
        if cid in explicit_conn_ids:
            raise ValueError(
                f"Inlet port on node '{nid}' generates connection id '{cid}' "
                f"which already exists in connections:. Remove one of the two."
            )
        if (from_id, nid) in explicit_edges:
            raise ValueError(
                f"Inlet port on node '{nid}' duplicates an explicit "
                f"connection from '{from_id}' to '{nid}'. Remove one of them."
            )
        conn_props: Dict[str, Any] = {}
        if "mass_flow_rate" in inlet and inlet["mass_flow_rate"] is not None:
            conn_props["mass_flow_rate"] = inlet["mass_flow_rate"]
        entry: Dict[str, Any] = {
            "id": cid,
            "type": "MassFlowController",
            "source": from_id,
            "target": nid,
            "properties": conn_props,
        }
        group = _node_group(node)
        if group:
            entry["group"] = group
        synthesized.append(entry)
        explicit_conn_ids.add(cid)
        explicit_edges.add((from_id, nid))
        mfc_inlets_by_target.setdefault(nid, []).append(cid)

    # Pass 2: outlet ports.
    for node in nodes:
        props = node.get("properties")
        if not isinstance(props, dict):
            continue
        outlet = props.pop("outlet", None)
        if outlet is None:
            continue
        if not isinstance(outlet, dict):
            raise ValueError(
                f"Node '{node.get('id')}' 'outlet' port must be a mapping, "
                f"got {type(outlet).__name__}."
            )
        nid = node["id"]
        to_id = outlet.get("to")
        if not to_id:
            raise ValueError(
                f"Node '{nid}' outlet port is missing required 'to:' field."
            )
        device = outlet.get("device", "PressureController")
        if device not in {"PressureController", "MassFlowController"}:
            raise ValueError(
                f"Node '{nid}' outlet port: unsupported device '{device}' "
                "(allowed: 'PressureController', 'MassFlowController')."
            )
        cid = f"{nid}_to_{to_id}"
        if cid in explicit_conn_ids:
            raise ValueError(
                f"Outlet port on node '{nid}' generates connection id '{cid}' "
                f"which already exists in connections:. Remove one of the two."
            )
        if (nid, to_id) in explicit_edges:
            raise ValueError(
                f"Outlet port on node '{nid}' duplicates an explicit "
                f"connection from '{nid}' to '{to_id}'. Remove one of them."
            )
        outlet_conn_props: Dict[str, Any] = {}
        if device == "PressureController":
            master = outlet.get("master")
            if master is None:
                candidates = [mid for mid in mfc_inlets_by_target.get(nid, []) if mid]
                if len(candidates) == 1:
                    master = candidates[0]
                elif not candidates:
                    raise ValueError(
                        f"Outlet PressureController on node '{nid}' has no "
                        "MassFlowController inlet to use as master. Declare "
                        "an inlet port (or an explicit inlet MFC) or switch "
                        "to 'device: MassFlowController'."
                    )
                else:
                    raise ValueError(
                        f"Outlet PressureController on node '{nid}' is "
                        f"ambiguous: {len(candidates)} candidate master MFCs "
                        f"({candidates}). Set 'master:' explicitly in the "
                        "outlet port, or switch to 'device: "
                        "MassFlowController' and omit 'mass_flow_rate' so "
                        "global conservation resolves it."
                    )
            outlet_conn_props["master"] = master
            outlet_conn_props["pressure_coeff"] = float(
                outlet.get("pressure_coeff", 0.0)
            )
        else:
            if "mass_flow_rate" in outlet and outlet["mass_flow_rate"] is not None:
                outlet_conn_props["mass_flow_rate"] = outlet["mass_flow_rate"]
        entry = {
            "id": cid,
            "type": device,
            "source": nid,
            "target": to_id,
            "properties": outlet_conn_props,
        }
        group = _node_group(node)
        if group:
            entry["group"] = group
        synthesized.append(entry)
        explicit_conn_ids.add(cid)
        explicit_edges.add((nid, to_id))

    connections.extend(synthesized)


def _sort_connections_by_master(config: Dict[str, Any]) -> None:
    """Reorder ``connections:`` so PressureControllers follow their masters.

    Cantera requires the primary :class:`~cantera.MassFlowController` to exist
    before a :class:`~cantera.PressureController` that references it.  The
    staged solver preserves list order within each stage so the ordering
    established here is the ordering used at build time.

    Raises
    ------
    ValueError
        When a PressureController references a master that does not exist or
        when the master graph has a cycle.
    """
    connections = config.get("connections")
    if not isinstance(connections, list) or len(connections) < 2:
        return

    by_id = {c.get("id"): c for c in connections if c.get("id")}

    # Dependency: every PC depends on its master.
    deps: Dict[str, set] = {cid: set() for cid in by_id}
    for cid, conn in by_id.items():
        if conn.get("type") == "PressureController":
            master = (conn.get("properties") or {}).get("master")
            if not master:
                continue
            if master not in by_id:
                raise ValueError(
                    f"PressureController '{cid}' references master "
                    f"'{master}' which is not a declared connection."
                )
            deps[cid].add(master)

    ordered: list = []
    ordered_ids: set = set()
    # Preserve original ordering of connections with no dependencies.
    remaining = [c.get("id") for c in connections if c.get("id")]
    progress = True
    while remaining and progress:
        progress = False
        still: list = []
        for cid in remaining:
            if deps[cid].issubset(ordered_ids):
                ordered.append(by_id[cid])
                ordered_ids.add(cid)
                progress = True
            else:
                still.append(cid)
        remaining = still
    if remaining:
        raise ValueError(
            "PressureController master graph has a cycle or unresolved "
            f"references: {remaining}"
        )
    # Keep connections that had no id at the end (rare; should not happen
    # after normalization).
    ordered.extend(c for c in connections if not c.get("id"))
    config["connections"] = ordered


def synthesize_default_group(config: Dict[str, Any]) -> None:
    """Inject a single-stage ``groups`` section when the YAML has none.

    Idempotent.  If ``config["groups"]`` is already a non-empty mapping, this
    function does nothing.  Otherwise it creates a ``default`` group with the
    global gas mechanism and ``solve: advance_to_steady_state``, and tags
    every node and connection with ``group: "default"`` so the staged solver
    picks them up.  Nodes or connections that already carry a group tag are
    left untouched (supports partial staging).
    """
    groups_cfg = config.get("groups")
    if groups_cfg:
        return

    default_mech = "gri30.yaml"
    phases = config.get("phases") or {}
    if isinstance(phases, dict):
        gas_phase = phases.get("gas") or {}
        if isinstance(gas_phase, dict):
            default_mech = gas_phase.get("mechanism") or default_mech

    config["groups"] = {
        "default": {
            "stage_order": 1,
            "mechanism": default_mech,
            "solve": "advance_to_steady_state",
        }
    }

    for node in config.get("nodes") or []:
        raw_props = node.get("properties")
        props = raw_props if isinstance(raw_props, dict) else {}
        has_group = bool(node.get("group") or props.get("group"))
        if not has_group:
            node["group"] = "default"

    for conn in config.get("connections") or []:
        raw_props = conn.get("properties")
        props = raw_props if isinstance(raw_props, dict) else {}
        has_group = bool(conn.get("group") or props.get("group"))
        if not has_group:
            conn["group"] = "default"


def propagate_terminal_pressure_defaults(config: Dict[str, Any]) -> None:
    """Propagate a declared process pressure from terminal nodes to their flow-connected peers.

    Groups nodes into connected components using only flow/logical connection edges
    (``MassFlowController``, ``PressureController``, ``Valve``).  ``Wall`` edges are
    excluded so ambient/satellite Reservoirs keep their own pressure.

    Within each component:
    - If zero or one distinct pressure is declared, no conflict exists.
    - If exactly one distinct pressure exists, fill missing ``properties.pressure``
      on all other nodes in the component (only ``Reservoir``, ``OutletSink``,
      and constant-pressure reactor kinds).
    - If multiple distinct pressures are declared, raise ``ValueError``.

    This is a defaulting pass.  Nodes that already carry a pressure that matches
    the component pressure are left unchanged.  The pass is a no-op when every
    node already has an explicit pressure (backward-compatible).
    """
    nodes: List[Dict[str, Any]] = config.get("nodes") or []
    connections: List[Dict[str, Any]] = config.get("connections") or []

    if not nodes:
        return

    # Flow-device connection types that carry process pressure.
    _FLOW_TYPES = frozenset({"MassFlowController", "PressureController", "Valve"})

    # Node types that should receive a defaulted pressure when missing.
    _PRESSURE_BEARING_TYPES = frozenset(
        {
            "Reservoir",
            "OutletSink",
            "IdealGasConstPressureReactor",
            "IdealGasConstPressureMoleReactor",
            "DesignPSR",
            "DesignTorchInstantaneousHeating",
            "DesignTorch",
            "DesignPFR",
            "DesignPFRThinShell",
            "DesignTubeFurnace",
        }
    )

    node_ids = [n["id"] for n in nodes]
    id_to_node = {n["id"]: n for n in nodes}

    # Build adjacency list from flow-only edges (undirected).
    adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for conn in connections:
        ctype = conn.get("type", "MassFlowController")
        if ctype not in _FLOW_TYPES:
            continue
        src = conn.get("source")
        tgt = conn.get("target")
        if src in adjacency and tgt in adjacency:
            adjacency[src].append(tgt)
            adjacency[tgt].append(src)

    # BFS/DFS to find connected components.
    visited: set = set()
    components: List[List[str]] = []
    for start in node_ids:
        if start in visited:
            continue
        component: List[str] = []
        stack = [start]
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            component.append(nid)
            stack.extend(adjacency[nid])
        components.append(component)

    # For each component, check declared pressures and propagate.
    for component in components:
        declared: Dict[str, float] = {}
        for nid in component:
            node = id_to_node[nid]
            raw_props = node.get("properties")
            props = raw_props if isinstance(raw_props, dict) else {}
            p = props.get("pressure")
            if p is not None:
                declared[nid] = float(p)

        distinct = set(round(v, 3) for v in declared.values())

        if len(distinct) > 1:
            # Multiple conflicting pressures in the same flow-connected component.
            details = ", ".join(f"'{nid}': {p:.1f} Pa" for nid, p in declared.items())
            raise ValueError(
                f"STONE v2 error: flow-connected component contains nodes with "
                f"conflicting process pressures ({details}). "
                "Declare process pressure on exactly one boundary node "
                "(e.g. the downstream OutletSink) and leave others unset. "
                "See STONE_SPECIFICATIONS.md."
            )

        if len(distinct) == 1:
            process_pressure = next(iter(declared.values()))
            for nid in component:
                node = id_to_node[nid]
                ntype = node.get("type", "")
                if ntype not in _PRESSURE_BEARING_TYPES:
                    continue
                props = node.setdefault("properties", {})
                if props.get("pressure") is None:
                    props["pressure"] = process_pressure


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a normalized config using Pydantic schema and return a plain dict.

    This performs structural validation and cross-references (IDs, source/target) without
    building any network.
    """
    # Import locally to avoid import costs when not needed
    from .validation import validate_normalized_config

    model = validate_normalized_config(config)
    as_dict = model.dict()
    # Drop None-valued optional metadata fields so downstream consumers that
    # use ``metadata.get(key, default)`` still see their fallback instead of
    # the explicit ``None`` produced by Pydantic's default serialization.
    meta = as_dict.get("metadata")
    if isinstance(meta, dict):
        cleaned = {k: v for k, v in meta.items() if v is not None}
        if not cleaned.get("extra"):
            cleaned.pop("extra", None)
        as_dict["metadata"] = cleaned
    return as_dict


def get_initial_config() -> Dict[str, Any]:
    """Load the initial configuration in YAML format with 🪨 STONE standard.

    Loads from configs/default.yaml using the elegant 🪨 STONE standard.
    """
    # Load from configs directory (YAML with 🪨 STONE standard)
    configs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs")
    stone_config_path = os.path.join(configs_dir, "default.yaml")

    if os.path.exists(stone_config_path):
        config = load_config_file(stone_config_path)
        normalized = normalize_config(config)
        return validate_config(normalized)
    else:
        raise FileNotFoundError(
            f"YAML configuration file with 🪨 STONE standard not found: {stone_config_path}"
        )


def get_initial_config_with_comments() -> tuple[Dict[str, Any], str]:
    """Load the initial configuration with comments preserved.

    Returns
    -------
        tuple: (normalized_config, original_yaml_string)
    """
    # Load from configs directory (YAML with 🪨 STONE standard)
    configs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs")
    stone_config_path = os.path.join(configs_dir, "default.yaml")

    if os.path.exists(stone_config_path):
        # Load with comments preserved
        config_with_comments = load_config_file_with_comments(
            stone_config_path
        )  # load YAML
        # Also read the raw file content to preserve original formatting
        with open(stone_config_path, "r", encoding="utf-8") as f:
            original_yaml = f.read()

        normalized_config = normalize_config(
            config_with_comments
        )  # convert to STONE format
        validated = validate_config(normalized_config)  # validate inputs
        return validated, original_yaml

    else:
        raise FileNotFoundError(
            f"YAML configuration file with 🪨 STONE standard not found: {stone_config_path}"
        )


def get_config_from_path(config_path: str) -> Dict[str, Any]:
    """Load configuration from a specific path."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = load_config_file(config_path)  # load YAML
    normalized = normalize_config(config)  # convert to STONE format
    return validate_config(normalized)  # validate inputs


def get_config_from_path_with_comments(config_path: str) -> tuple[Dict[str, Any], str]:
    """Load configuration from a specific path with comments preserved.

    Returns
    -------
    tuple
        (normalized_config, original_yaml_string)
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config_with_comments = load_config_file_with_comments(config_path)  # load YAML
    with open(config_path, "r", encoding="utf-8") as f:
        original_yaml = f.read()
    normalized = normalize_config(
        config_with_comments
    )  # convert to STONE format with comments
    return validate_config(normalized), original_yaml  # validate inputs


def convert_to_stone_format(config: dict) -> dict:
    """Convert internal format back to new STONE schema for file saving."""
    stone_config = {}

    # Copy metadata section as-is
    if "metadata" in config:
        stone_config["metadata"] = config["metadata"]

    # Copy phases and settings sections directly (STONE standard)
    if "phases" in config:
        stone_config["phases"] = config["phases"]

    if "settings" in config:
        stone_config["settings"] = config["settings"]

    # Convert nodes to STONE format
    if "nodes" in config:
        stone_config["nodes"] = []
        for node in config["nodes"]:
            # Build node with id first, then type as key containing properties
            node_type = node.get("type", "IdealGasReactor")
            props = dict(node.get("properties", {}) or {})
            mech_override = props.pop("mechanism", None)
            stone_node = {"id": node["id"], node_type: props}
            if mech_override is not None:
                stone_node["mechanism"] = mech_override
            stone_config["nodes"].append(stone_node)

    # Convert connections (same structure in new format)
    if "connections" in config:
        stone_config["connections"] = []
        for connection in config["connections"]:
            # Build connection with id first, then type as key, then source/target
            connection_type = connection.get("type", "MassFlowController")
            stone_connection = {
                "id": connection["id"],
                connection_type: connection.get("properties", {}),
                "source": connection["source"],
                "target": connection["target"],
            }
            stone_config["connections"].append(stone_connection)

    # Carry-through `output` section (STONE standard extension)
    if "output" in config:
        stone_config["output"] = config["output"]

    return stone_config


def yaml_to_string_with_comments(data) -> str:
    """Convert data to YAML string while preserving comments."""
    from io import StringIO

    yaml_obj = get_yaml_with_comments()
    stream = StringIO()
    yaml_obj.dump(data, stream)
    return stream.getvalue()


def load_yaml_string_with_comments(yaml_str: str):
    """Load YAML string while preserving comments."""
    from io import StringIO

    yaml_obj = get_yaml_with_comments()
    stream = StringIO(yaml_str)
    return yaml_obj.load(stream)


def save_config_to_file_with_comments(
    config: dict, file_path: str, original_yaml_str: Optional[str] = None
):
    """Save configuration to file, preserving comments when possible."""
    stone_config = convert_to_stone_format(config)

    if original_yaml_str:
        # Try to preserve the original structure and comments
        try:
            # Load the original YAML with comments
            original_data = load_yaml_string_with_comments(original_yaml_str)

            # Update the original data with new values while preserving structure
            updated_data = _update_yaml_preserving_comments(original_data, stone_config)

            # Save with comments preserved
            yaml_obj = get_yaml_with_comments()
            with open(file_path, "w", encoding="utf-8") as f:
                yaml_obj.dump(updated_data, f)
            return
        except Exception as e:
            print(f"Warning: Could not preserve comments, using standard format: {e}")

    # Fallback: save without comment preservation
    yaml_str = yaml_to_string_with_comments(stone_config)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)


def _update_yaml_preserving_comments(original_data, new_data):
    """Update YAML data while preserving comments and structure.

    This function recursively updates the original YAML structure with new values
    while preserving all comments and formatting.
    """
    # Import here to avoid circular imports
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if not isinstance(original_data, dict) or not isinstance(new_data, dict):
        return new_data

    # Create a copy that preserves comments and structure
    if isinstance(original_data, CommentedMap):
        updated = CommentedMap()
        # Copy original data to preserve comments
        for key, value in original_data.items():
            updated[key] = value
    else:
        updated = (
            original_data.copy()
            if hasattr(original_data, "copy")
            else dict(original_data)
        )

    # Update with new values
    for key, new_value in new_data.items():
        if key in updated:
            original_value = updated[key]

            # Handle dictionaries recursively
            if isinstance(original_value, dict) and isinstance(new_value, dict):
                updated[key] = _update_yaml_preserving_comments(
                    original_value, new_value
                )

            # Handle arrays/lists - this is the key fix
            elif isinstance(original_value, (list, CommentedSeq)) and isinstance(
                new_value, list
            ):
                updated[key] = _update_yaml_array_preserving_comments(
                    original_value, new_value
                )

            # For scalar values, just update
            else:
                updated[key] = new_value
        else:
            # New key, add it
            updated[key] = new_value

    return updated


def _update_yaml_array_preserving_comments(original_array, new_array):
    """Update an array while preserving comments on array items.

    This function matches items in the arrays by their 'id' field and preserves
    comments on each item while updating their values.
    """
    from ruamel.yaml.comments import CommentedSeq

    # Create a new commented sequence to preserve array comments
    if isinstance(original_array, CommentedSeq):
        updated_array = CommentedSeq()
        # Copy array-level comments by copying the entire original array first
        # then updating its contents
        for item in original_array:
            updated_array.append(item)

        # Now clear and rebuild with updated items
        updated_array.clear()
    else:
        updated_array = []

    # Create a mapping of original items by their ID for easy lookup
    original_by_id = {}
    for item in original_array:
        if isinstance(item, dict) and "id" in item:
            original_by_id[item["id"]] = item

    # Process each new item
    for new_item in new_array:
        if isinstance(new_item, dict) and "id" in new_item:
            item_id = new_item["id"]

            # If we have an original item with the same ID, merge it
            if item_id in original_by_id:
                original_item = original_by_id[item_id]
                updated_item = _update_yaml_item_preserving_comments(
                    original_item, new_item
                )
                updated_array.append(updated_item)
            else:
                # New item, add as-is
                updated_array.append(new_item)
        else:
            # Item without ID, add as-is
            updated_array.append(new_item)

    return updated_array


def _update_yaml_item_preserving_comments(original_item, new_item):
    """Update a single YAML item while preserving its STONE format structure.

    This function handles the specific case of nodes and connections
    which have a special structure in STONE format.
    """
    from ruamel.yaml.comments import CommentedMap

    if not isinstance(original_item, dict) or not isinstance(new_item, dict):
        return new_item

    # Create a copy that preserves comments and structure
    if isinstance(original_item, CommentedMap):
        updated_item = CommentedMap()
        # Copy original data to preserve comments
        for key, value in original_item.items():
            updated_item[key] = value
    else:
        updated_item = original_item.copy()

    # For STONE format, we need to preserve the structure but update values
    # The new_item comes in STONE format, so we can directly update
    for key, new_value in new_item.items():
        if key == "id":
            # Always update the ID
            updated_item[key] = new_value
        elif key in ["source", "target"]:
            # For connections, update source/target
            updated_item[key] = new_value
        elif key in updated_item:
            # For other keys that exist in original (like component type keys)
            if isinstance(updated_item[key], dict) and isinstance(new_value, dict):
                # Recursively update nested dictionaries
                updated_item[key] = _update_yaml_preserving_comments(
                    updated_item[key], new_value
                )
            else:
                updated_item[key] = new_value

    return updated_item


def load_config_file_with_py_support(
    config_path: str, verbose: bool = False
) -> Tuple[Dict[str, Any], str]:
    """Load configuration file with automatic Python to YAML conversion support.

    Logic:
    1. If .py file: convert to .yaml first, then load the .yaml
    2. If .yaml/.yml file: load directly
    3. Always return loaded config from a YAML file

    Args:
        config_path: Path to configuration file (.yaml, .yml, or .py)
        verbose: Enable verbose output

    Returns
    -------
        Tuple of (config_dict, yaml_file_path)

    Raises
    ------
        ValueError: If file type is not supported
        FileNotFoundError: If file doesn't exist
        RuntimeError: If conversion fails
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    _, ext = os.path.splitext(config_path.lower())

    # Step 0: Convert Python to YAML if needed (preliminary conversion step)
    yaml_path = config_path

    if ext == ".py":
        from .parser import convert_py_to_yaml

        if verbose:
            print(f"[Boulder] Detected Python file: {config_path}")
            print("[Boulder] Converting to YAML using sim2stone...")

        yaml_path = convert_py_to_yaml(config_path, verbose=verbose)

    elif ext not in [".yaml", ".yml"]:
        raise ValueError(
            f"Unsupported file format. Supported formats: .py, .yaml, .yml. Got: {ext}"
        )

    # Step 1 & 2: Common YAML processing pipeline (for both original YAML and converted Python)
    if verbose:
        print(f"[Boulder] Loading YAML file: {yaml_path}")

    config = load_config_file(yaml_path)
    return config, yaml_path


def load_config_file_with_py_support_and_comments(
    config_path: str, verbose: bool = False
) -> Tuple[Dict[str, Any], str, str]:
    """Load configuration file with Python support, preserving comments.

    Logic:
    1. If .py file: convert to .yaml first
    2. Always load from the resulting .yaml file with comments preserved

    Args:
        config_path: Path to configuration file (.yaml, .yml, or .py)
        verbose: Enable verbose output

    Returns
    -------
        Tuple of (config_dict, original_yaml_string, yaml_file_path)
    """
    # Step 1: Handle conversion if needed, get the YAML path
    config, yaml_path = load_config_file_with_py_support(config_path, verbose)

    # Step 2: Always read the YAML file with comments preserved
    with open(yaml_path, "r", encoding="utf-8") as f:
        original_yaml = f.read()

    return config, original_yaml, yaml_path
