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
        "continuation",
        "signals",
        "bindings",
        "scopes",
    }
)

# Mapping from solver.kind → implied solver.mode.
_SOLVER_KIND_TO_MODE: Dict[str, str] = {
    "advance_to_steady_state": "steady",
    "solve_steady": "steady",
    "advance": "transient",
    "advance_grid": "transient",
    "micro_step": "transient",
}


def _resolve_and_validate_solver_mode(
    solver: Dict[str, Any], context: str
) -> Dict[str, Any]:
    """Return a copy of *solver* with ``mode`` filled in and validated.

    Rules:

    - If ``mode`` is absent, derive it from ``kind`` (default
      ``advance_to_steady_state`` → ``steady``).
    - If ``mode`` is present and contradicts ``kind``, raise ``ValueError``.
    - The returned dict always has a ``mode`` key.

    Parameters
    ----------
    solver:
        The resolved solver dict (already merged global + per-stage).
    context:
        A short descriptive string for error messages (e.g. ``"stage 'psr'"``.
    """
    kind = solver.get("kind", "advance_to_steady_state")
    implied_mode = _SOLVER_KIND_TO_MODE.get(kind, "steady")
    explicit_mode = solver.get("mode")
    if explicit_mode is not None:
        if explicit_mode not in ("steady", "transient"):
            raise ValueError(
                f"STONE v2 error: {context} solver.mode '{explicit_mode}' is not valid. "
                "Allowed values: 'steady', 'transient'. See STONE_SPECIFICATIONS.md."
            )
        if explicit_mode != implied_mode:
            raise ValueError(
                f"STONE v2 error: {context} solver.mode: {explicit_mode} is incompatible "
                f"with solver.kind: {kind} (which implies mode: {implied_mode}). "
                "See STONE_SPECIFICATIONS.md."
            )
    return {**solver, "mode": implied_mode}


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

# Built-in Cantera (non-extensible) const-pressure kind strings.
_CONST_PRESSURE_KINDS: frozenset = frozenset(
    {
        "IdealGasConstPressureReactor",
        "IdealGasConstPressureMoleReactor",
        "ConstPressureReactor",
        "ConstPressureMoleReactor",
    }
)


def _is_const_pressure_kind(kind: str) -> bool:
    """Return True when *kind* operates at constant pressure.

    Detection order:
    1. Explicit built-in Cantera set (``_CONST_PRESSURE_KINDS``).
    2. Cantera naming convention: ``"ConstPressure"`` substring in the kind
       string itself (covers ``Extensible*`` variant kind names when used
       directly as YAML kind strings).
    3. Plugin registry: ``issubclass`` check against all Cantera const-pressure
       base classes (both standard and ``Extensible*`` roots).  Plugin reactors
       like those in Bloc inherit from ``ct.ExtensibleIdealGasConstPressureMoleReactor``
       and are caught here automatically via the registered ``reactor_class``.
    """
    if kind in _CONST_PRESSURE_KINDS or "ConstPressure" in kind:
        return True
    from boulder.schema_registry import is_const_pressure_kind as _reg_check

    return _reg_check(kind)


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
    for k in (
        "output",
        "export",
        "sweeps",
        "scenarios",
        "continuation",
        "signals",
        "bindings",
        "scopes",
    ):
        if k in raw:
            result[k] = raw[k]

    result["nodes"] = nodes
    result["connections"] = connections
    # Propagate any settings.solver defaults into the synthesized default group
    _settings = raw.get("settings") or {}
    _settings_solver = _settings.get("solver") if isinstance(_settings, dict) else None
    _default_group_solver: Dict[str, Any] = {"kind": "advance_to_steady_state"}
    if isinstance(_settings_solver, dict):
        _default_group_solver = {**_default_group_solver, **_settings_solver}
    _default_group_solver = _resolve_and_validate_solver_mode(
        _default_group_solver, "default stage"
    )
    result["groups"] = {
        "default": {
            "stage_order": 1,
            "mechanism": default_mech,
            "solver": _default_group_solver,
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

    # Valid solver kind values
    _VALID_SOLVER_KINDS = frozenset(
        {
            "advance_to_steady_state",
            "solve_steady",
            "advance",
            "advance_grid",
            "micro_step",
        }
    )
    # Kinds that require a top-level legacy advance_time (legacy path only)
    _ADVANCE_TIME_REQUIRED_LEGACY = frozenset({"advance"})

    # Validate stage metadata (solve/solver, advance_time)
    for sid, smeta in stages_meta.items():
        if not isinstance(smeta, dict):
            raise ValueError(
                f"STONE v2 error: stage '{sid}' metadata must be a mapping."
            )

        # ----- New-style solver: block -----
        if "solver" in smeta:
            solver_block = smeta["solver"]
            if not isinstance(solver_block, dict):
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' has 'solver:' that is not a mapping. "
                    "See STONE_SPECIFICATIONS.md."
                )
            kind = solver_block.get("kind", "advance_to_steady_state")
            if kind not in _VALID_SOLVER_KINDS:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' solver.kind '{kind}' is not valid. "
                    f"Allowed: {sorted(_VALID_SOLVER_KINDS)}. "
                    "See STONE_SPECIFICATIONS.md."
                )
            if kind == "advance" and "advance_time" not in solver_block:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' uses solver.kind: advance but is "
                    "missing 'advance_time:' in the solver block. "
                    "See STONE_SPECIFICATIONS.md."
                )
            if kind == "advance_grid" and "grid" not in solver_block:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' uses solver.kind: advance_grid but "
                    "is missing 'grid:' in the solver block. "
                    "See STONE_SPECIFICATIONS.md."
                )
            if kind == "micro_step":
                for req in ("t_total", "chunk_dt", "max_dt"):
                    if req not in solver_block:
                        raise ValueError(
                            f"STONE v2 error: stage '{sid}' uses solver.kind: micro_step "
                            f"but is missing '{req}:' in the solver block. "
                            "See STONE_SPECIFICATIONS.md."
                        )
            # Legacy solve: / advance_time: must not coexist with solver: block
            if "solve" in smeta:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' declares both 'solver:' and legacy "
                    "'solve:'. Use only 'solver:'. "
                    "See STONE_SPECIFICATIONS.md."
                )
        else:
            # ----- Legacy solve:/advance_time: form (deprecated) -----
            solve = smeta.get("solve")
            if solve is None:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' has neither 'solver:' nor legacy "
                    "'solve:'. One is required. "
                    "See STONE_SPECIFICATIONS.md."
                )
            if solve not in _VALID_SOLVER_KINDS:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' has invalid 'solve:' value '{solve}'. "
                    f"Allowed values: {sorted(_VALID_SOLVER_KINDS)}. "
                    "See STONE_SPECIFICATIONS.md."
                )
            has_at = "advance_time" in smeta
            if solve in _ADVANCE_TIME_REQUIRED_LEGACY and not has_at:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' uses solve: {solve} but is missing "
                    "'advance_time:'. See STONE_SPECIFICATIONS.md."
                )
            if solve not in _ADVANCE_TIME_REQUIRED_LEGACY and has_at:
                raise ValueError(
                    f"STONE v2 error: stage '{sid}' uses solve: {solve} "
                    "but declares 'advance_time:' which is only valid for 'advance'. "
                    "See STONE_SPECIFICATIONS.md."
                )
            import warnings  # noqa: PLC0415

            warnings.warn(
                f"Stage '{sid}': legacy 'solve:' / 'advance_time:' keys are deprecated. "
                "Use 'solver: { kind: ... }' instead. "
                "See STONE_SPECIFICATIONS.md.",
                DeprecationWarning,
                stacklevel=8,
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

    # Global settings.solver defaults
    _settings_g = raw.get("settings") or {}
    _global_solver_defaults: Dict[str, Any] = {}
    if isinstance(_settings_g, dict):
        _sv = _settings_g.get("solver")
        if isinstance(_sv, dict):
            _global_solver_defaults = dict(_sv)

    # Build groups section from stage metadata (topological order)
    groups: Dict[str, Any] = {}
    for order_idx, sid in enumerate(ordered_stages):
        smeta = stages_meta[sid]
        # Resolve solver block: new-style "solver:" wins; legacy "solve:" is promoted
        if "solver" in smeta:
            per_stage_solver = dict(smeta["solver"])
        else:
            # Legacy form: promoted to solver.kind (warning already issued in validation)
            from .utils import coerce_unit_string  # noqa: PLC0415

            per_stage_solver = {"kind": str(smeta["solve"])}
            if "advance_time" in smeta:
                at_raw = smeta["advance_time"]
                # Support unit-bearing strings like "1 ms"
                at_si = coerce_unit_string(at_raw, "advance_time")
                per_stage_solver["advance_time"] = float(at_si)
        resolved_solver = {**_global_solver_defaults, **per_stage_solver}
        resolved_solver = _resolve_and_validate_solver_mode(
            resolved_solver, f"stage '{sid}'"
        )

        group_entry: Dict[str, Any] = {
            "stage_order": order_idx + 1,
            "mechanism": smeta.get("mechanism", "gri30.yaml"),
            "solver": resolved_solver,
        }
        groups[sid] = group_entry

    result = {k: raw[k] for k in ("metadata", "phases", "settings") if k in raw}
    for k in (
        "output",
        "export",
        "sweeps",
        "scenarios",
        "continuation",
        "signals",
        "bindings",
        "scopes",
    ):
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
                # Nodes always carry a kind key in STONE v2; ``kind`` is only
                # Optional for connections (logical inter-stage edges).
                assert kind is not None
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
                n["__synthesized"] = True
                nodes.append(n)
                by_node_id[n["id"]] = n
            elif {k: v for k, v in existing.items() if k != "__synthesized"} != n:
                raise ValueError(
                    f"Composite unfold collision: node id '{n['id']}' "
                    f"emitted by unfolder for '{node['id']}' conflicts "
                    "with an existing node.\n"
                    f"  Composite reactor '{node['id']}' (type '{node.get('type')}') "
                    f"automatically generates a satellite node named '{n['id']}'.\n"
                    "  Fix: remove or rename the explicit node whose id matches "
                    f"'{n['id']}' in your YAML — it is managed internally and must "
                    "not be declared by the user."
                )
        for c in result.get("connections", []):
            existing = by_conn_id.get(c["id"])
            if existing is None:
                c["__synthesized"] = True
                conns.append(c)
                by_conn_id[c["id"]] = c
            elif {k: v for k, v in existing.items() if k != "__synthesized"} != c:
                raise ValueError(
                    f"Composite unfold collision: connection id '{c['id']}' "
                    f"emitted by unfolder for '{node['id']}' conflicts "
                    "with an existing connection.\n"
                    f"  Composite reactor '{node['id']}' (type '{node.get('type')}') "
                    f"automatically generates a satellite connection named '{c['id']}'.\n"
                    "  Fix: remove or rename the explicit connection whose id matches "
                    f"'{c['id']}' in your YAML — it is managed internally and must "
                    "not be declared by the user."
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
          - id: reactor
            IdealGasConstPressureMoleReactor:
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

    # Tag every port-shortcut-derived connection as synthesized so the live
    # YAML sync endpoint can filter them out (they are never in the user's file).
    for entry in synthesized:
        entry["__synthesized"] = True
    # Also record that port shortcuts were present in this config so that the
    # sync endpoint can reject requests for configs derived from inline-port YAML.
    if synthesized:
        config["__has_inline_ports"] = True

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

    _settings_solver = None
    _settings = config.get("settings")
    if isinstance(_settings, dict):
        _settings_solver = _settings.get("solver")
    _default_group_solver: Dict[str, Any] = {"kind": "advance_to_steady_state"}
    if isinstance(_settings_solver, dict):
        _default_group_solver = {**_default_group_solver, **_settings_solver}
    _default_group_solver = _resolve_and_validate_solver_mode(
        _default_group_solver, "default stage"
    )

    config["groups"] = {
        "default": {
            "stage_order": 1,
            "mechanism": default_mech,
            "solver": _default_group_solver,
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
    # Reservoirs and sinks are always pressure-bearing; any const-pressure
    # reactor kind (detected by the ``"ConstPressure"`` naming convention) is
    # also pressure-bearing.
    _PRESSURE_BEARING_SINKS = frozenset({"Reservoir", "OutletSink"})

    def _is_pressure_bearing(kind: str) -> bool:
        return kind in _PRESSURE_BEARING_SINKS or _is_const_pressure_kind(kind)

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
                if not _is_pressure_bearing(ntype):
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


def _internal_node_to_stone_v2_item(node: Dict[str, Any]) -> Dict[str, Any]:
    """Map one internal node dict to a STONE v2 stage/network list item."""
    node_type = node.get("type", "IdealGasReactor")
    props = dict(node.get("properties", {}) or {})
    props.pop("__synthesized", None)
    mech_from_props = props.pop("mechanism", None)

    # For const-pressure reactor kinds, ``pressure`` is the network operating
    # pressure and lives inside the ``initial:`` block (seeding state).
    # ``propagate_terminal_pressure_defaults`` also writes it to the top-level
    # properties dict, which causes a duplicate when the YAML is re-emitted.
    # Strip the outer ``pressure`` when ``initial.pressure`` already carries it.
    initial = props.get("initial")
    if (
        _is_const_pressure_kind(node_type)
        and isinstance(initial, dict)
        and "pressure" in initial
        and "pressure" in props
    ):
        props.pop("pressure")

    stone_node: Dict[str, Any] = {"id": node["id"], node_type: props}
    top_mech = node.get("mechanism")
    if top_mech is not None:
        stone_node["mechanism"] = top_mech
    elif mech_from_props is not None:
        stone_node["mechanism"] = mech_from_props
    for fld in ("description", "label"):
        if fld in node:
            stone_node[fld] = node[fld]
    metadata = node.get("metadata")
    if metadata is not None:
        # Strip internal private key before emitting YAML
        metadata = {k: v for k, v in metadata.items() if k != "__synthesized"}
        if metadata:
            stone_node["metadata"] = metadata
    return stone_node


def _internal_connection_to_stone_v2_item(conn: Dict[str, Any]) -> Dict[str, Any]:
    """Map one internal connection dict to a STONE v2 stage/network list item."""
    if conn.get("logical"):
        item: Dict[str, Any] = {
            "id": conn["id"],
            "source": conn["source"],
            "target": conn["target"],
        }
        props = conn.get("properties") or {}
        if isinstance(props, dict) and props.get("mass_flow_rate") is not None:
            item["mass_flow_rate"] = props["mass_flow_rate"]
        if conn.get("mechanism_switch") is not None:
            item["mechanism_switch"] = conn["mechanism_switch"]
        if conn.get("metadata") is not None:
            item["metadata"] = conn["metadata"]
        return item

    connection_type = conn.get("type", "MassFlowController")
    props = dict(conn.get("properties", {}) or {})
    props.pop("__synthesized", None)
    stone_conn: Dict[str, Any] = {
        "id": conn["id"],
        connection_type: props,
        "source": conn["source"],
        "target": conn["target"],
    }
    if conn.get("mechanism_switch") is not None:
        stone_conn["mechanism_switch"] = conn["mechanism_switch"]
    metadata = conn.get("metadata")
    if metadata is not None:
        metadata = {k: v for k, v in metadata.items() if k != "__synthesized"}
        if metadata:
            stone_conn["metadata"] = metadata
    return stone_conn


def convert_to_stone_format(config: dict) -> dict:
    """Convert internal (normalized) format to STONE v2 authoring dict for YAML export.

    Single-stage configs become a top-level ``network:`` list. Multi-stage configs
    become ``stages:`` metadata plus one top-level list per stage id. Legacy
    top-level ``nodes:`` / ``connections:`` are not emitted (those imply STONE v1).
    """
    stone_config: Dict[str, Any] = {}

    if "metadata" in config:
        stone_config["metadata"] = config["metadata"]

    if "phases" in config:
        stone_config["phases"] = config["phases"]

    if "settings" in config:
        stone_config["settings"] = config["settings"]

    for passthrough in ("output", "export", "sweeps", "scenarios"):
        if passthrough in config:
            stone_config[passthrough] = config[passthrough]

    nodes: List[Dict[str, Any]] = list(config.get("nodes") or [])
    connections: List[Dict[str, Any]] = list(config.get("connections") or [])
    groups: Dict[str, Any] = dict(config.get("groups") or {})

    use_network_key = (not groups) or (len(groups) == 1 and "default" in groups)

    if use_network_key:
        stone_config["network"] = [
            _internal_node_to_stone_v2_item(n) for n in nodes
        ] + [_internal_connection_to_stone_v2_item(c) for c in connections]
        return stone_config

    stage_ids_ordered = sorted(
        groups.keys(),
        key=lambda sid: (groups[sid].get("stage_order", 0), sid),
    )
    stages_meta: Dict[str, Any] = {}
    for sid in stage_ids_ordered:
        g = groups[sid]
        if not isinstance(g, dict):
            continue
        meta: Dict[str, Any] = {
            "mechanism": g.get("mechanism", "gri30.yaml"),
            "solve": g["solve"],
        }
        if "advance_time" in g:
            meta["advance_time"] = g["advance_time"]
        stages_meta[sid] = meta

    stone_config["stages"] = stages_meta

    for sid in stage_ids_ordered:
        stage_nodes = [n for n in nodes if n.get("group") == sid]
        stage_conns = [c for c in connections if c.get("group") == sid]
        stone_config[sid] = [
            _internal_node_to_stone_v2_item(n) for n in stage_nodes
        ] + [_internal_connection_to_stone_v2_item(c) for c in stage_conns]

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


def _yaml_has_inline_ports(ruamel_tree: Any) -> bool:
    """Return True if any node in *ruamel_tree* declares an inline port shortcut.

    Inline ports are ``inlet:`` or ``outlet:`` keys nested inside a node's
    component-property dict in a STONE v2 YAML.
    """
    _PORT_KEYS = {"inlet", "outlet"}
    _NON_KIND_TOP = {
        "id",
        "source",
        "target",
        "metadata",
        "mechanism",
        "description",
        "label",
        "mechanism_switch",
        "group",
        "mass_flow_rate",
        "stages",
    }

    def _check_item(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        for k, v in item.items():
            if k not in _NON_KIND_TOP and isinstance(v, dict):
                if _PORT_KEYS.intersection(v.keys()):
                    return True
        return False

    if not isinstance(ruamel_tree, dict):
        return False

    # Walk all list values at the top level (network:, stage lists).
    for val in ruamel_tree.values():
        if isinstance(val, list):
            for item in val:
                if _check_item(item):
                    return True
    return False


def _collect_authored_ids(ruamel_tree: Any) -> set:
    """Return the set of ``id`` values present in the original YAML network/stage lists.

    These are the IDs the user actually wrote.  Any ID produced by an expander
    (``expand_composite_kinds``, ``expand_port_shortcuts``) will NOT be in this
    set and should be treated as synthesized.
    """
    ids: set = set()
    if not isinstance(ruamel_tree, dict):
        return ids
    for val in ruamel_tree.values():
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "id" in item:
                    ids.add(item["id"])
    return ids


def _fresh_normalize_original(
    original_yaml_str: str,
) -> Tuple[set, Dict[str, Dict[str, Any]]]:
    """Re-normalize *original_yaml_str* and return synthesized IDs + default properties.

    Returns
    -------
    tuple
        ``(synthesized_ids, default_props_by_id)``

        * ``synthesized_ids`` – IDs produced by expanders (not in the original
          YAML tree).
        * ``default_props_by_id`` – ``{node_or_conn_id: properties_dict}`` for
          every authored node/connection in the fresh normalize result.  These
          are the normalization-default properties that should NOT be injected
          back into the YAML when they weren't explicitly authored.
    """
    try:
        original_data = load_yaml_string_with_comments(original_yaml_str)
        authored_ids = _collect_authored_ids(original_data)
        plain = _to_plain_dict(original_data)
        normalized = normalize_config(plain)
        all_ids: set = set()
        default_props: Dict[str, Dict[str, Any]] = {}
        for n in normalized.get("nodes") or []:
            nid = n.get("id")
            if nid:
                all_ids.add(nid)
                default_props[nid] = n.get("properties") or {}
        for c in normalized.get("connections") or []:
            cid = c.get("id")
            if cid:
                all_ids.add(cid)
                default_props[cid] = c.get("properties") or {}
        return all_ids - authored_ids, default_props
    except Exception:
        return set(), {}


def _collect_synthesized_ids_from_fresh_normalize(original_yaml_str: str) -> set:
    """Re-normalize *original_yaml_str* and return IDs added by expanders."""
    synthesized_ids, _ = _fresh_normalize_original(original_yaml_str)
    return synthesized_ids


def merge_config_into_yaml(
    config: dict,
    original_yaml_str: str,
) -> Tuple[str, List[str]]:
    """Merge *config* into *original_yaml_str* while preserving comments and units.

    This is the shared backend entry-point used by both the live-sync API
    endpoint (``POST /api/configs/sync``) and
    :func:`save_config_to_file_with_comments`.

    Parameters
    ----------
    config:
        Normalized (SI) internal config dict, as stored in the frontend Zustand
        store.
    original_yaml_str:
        The verbatim YAML text from the user's file, as loaded by the frontend.

    Returns
    -------
    tuple
        ``(yaml_string, warnings)`` — the merged YAML text plus any non-fatal
        warning messages (e.g. Pint back-conversion failures).

    Raises
    ------
    ValueError
        If the config cannot be safely synced into the original YAML:

        * Inline port shortcuts (``inlet:`` / ``outlet:`` on nodes) were
          detected in the original YAML — the mapping is lossy and sync cannot
          reconstruct it.
        * Top-level shape mismatch — original used ``network:`` but current
          config would produce ``stages:`` (or vice versa).
    """
    from .yaml_unit_map import apply_unit_map_inplace, build_unit_map  # noqa: PLC0415

    # 1. Parse original YAML preserving comments.
    original_data = load_yaml_string_with_comments(original_yaml_str)

    # 2. Build unit_map from original tree before any mutation.
    unit_map = build_unit_map(original_data)

    # 3. Detect inline port shortcuts in the original YAML by walking its
    #    network/stage lists without a full normalize cycle.
    if _yaml_has_inline_ports(original_data):
        raise ValueError(
            "Inline port shortcuts (inlet: / outlet: on a node) are not yet "
            "supported by the YAML live-sync editor. Convert them to explicit "
            "connections: entries in your file and reopen."
        )

    # 4. Build STONE representation from config, filtering synthesized items.
    #
    # The ``__synthesized`` flag is set by expand_composite_kinds /
    # expand_port_shortcuts but is stripped by ``validate_config`` (Pydantic
    # serialisation).  The frontend therefore sends back the validated config
    # without ``__synthesized`` on satellite nodes.
    #
    # Two-source filter:
    # a) Explicit ``__synthesized=True`` flag (present on fresh normalize; may
    #    be absent on configs that passed through validate_config).
    # b) ID is in ``fresh_synthesized_ids``: IDs produced by expanders when
    #    we re-normalize the original YAML here, minus IDs already in the
    #    original YAML tree.  These are always synthesized satellites.
    #
    # An item absent from the original YAML AND not in fresh_synthesized_ids
    # was added by the GUI → keep it.
    fresh_synthesized_ids, default_props_by_id = _fresh_normalize_original(
        original_yaml_str
    )

    def _should_keep(item: dict) -> bool:
        if item.get("__synthesized"):
            return False
        item_id = item.get("id")
        if item_id and item_id in fresh_synthesized_ids:
            return False
        return True

    config_for_stone = dict(config)
    config_for_stone["nodes"] = [
        n for n in (config.get("nodes") or []) if _should_keep(n)
    ]
    config_for_stone["connections"] = [
        c for c in (config.get("connections") or []) if _should_keep(c)
    ]
    stone = convert_to_stone_format(config_for_stone)

    # 5. Shape-conflict guard: original uses network: XOR stages:.
    orig_has_network = "network" in original_data
    orig_has_stages = "stages" in original_data
    stone_has_network = "network" in stone
    stone_has_stages = "stages" in stone

    if orig_has_network and stone_has_stages:
        raise ValueError(
            "Shape conflict: the original YAML uses a flat network: list but "
            "the current configuration has multiple stages. Stage management "
            "via the YAML editor is not yet supported."
        )
    if orig_has_stages and stone_has_network:
        raise ValueError(
            "Shape conflict: the original YAML uses stages: but the current "
            "configuration has no stage grouping. Removing stages via the "
            "YAML editor is not yet supported."
        )

    # 6. Warn about anchors/aliases (limited support).
    warnings: List[str] = []
    if "&" in original_yaml_str or "*" in original_yaml_str:
        warnings.append(
            "The original YAML contains anchors (&) or aliases (*). "
            "Comment and value preservation for anchored nodes is not "
            "guaranteed after sync."
        )

    # 7. Strip top-level keys from stone that are absent from the original YAML.
    #    Keys like ``settings`` and ``output`` are injected by
    #    ``convert_to_stone_format`` from normalization artifacts; if the user
    #    didn't write them they must not appear in the merged output.
    stone_for_merge = {k: v for k, v in stone.items() if k in original_data}

    # 8. Merge STONE dict into original ruamel tree in-place.
    _update_yaml_preserving_comments(
        original_data, stone_for_merge, default_props_by_id=default_props_by_id
    )

    # 9. Apply unit map: replace SI floats with original unit strings.
    unit_warnings = apply_unit_map_inplace(original_data, unit_map, config)
    warnings.extend(unit_warnings)

    # 10. Dump to string using the same sequence indentation as the original.
    yaml_str = _yaml_to_string_matching_indent(original_data, original_yaml_str)
    return yaml_str, warnings


def _detect_sequence_indent(yaml_str: str) -> Optional[int]:
    """Return the number of spaces before the first ``-`` list item, or None."""
    import re as _re

    m = _re.search(r"^( +)-", yaml_str, _re.MULTILINE)
    if m:
        return len(m.group(1))
    return None


def _yaml_to_string_matching_indent(data: Any, original_yaml_str: str) -> str:
    """Dump *data* to YAML string, matching the sequence indentation of *original_yaml_str*.

    The original file may use ``  - `` (2-space) indentation for list items.
    ruamel's default (sequence=2, offset=0) emits ``- `` at column 0.  We
    detect the original indent and adjust the dump settings accordingly.
    """
    from io import StringIO

    yaml_obj = get_yaml_with_comments()
    orig_indent = _detect_sequence_indent(original_yaml_str)
    if orig_indent is not None and orig_indent > 0:
        # sequence=indent+2 (dash + space + content), offset=indent
        yaml_obj.indent(mapping=2, sequence=orig_indent + 2, offset=orig_indent)
    stream = StringIO()
    yaml_obj.dump(data, stream)
    return stream.getvalue()


def _to_plain_dict(data: Any) -> Any:
    """Recursively convert ruamel CommentedMap/Seq to plain Python dicts/lists.

    Defined here as a module-level helper so it can be used by both the API
    routes and :func:`merge_config_into_yaml` without an import cycle.
    """
    if isinstance(data, dict):
        return {k: _to_plain_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_to_plain_dict(item) for item in data]
    return data


def save_config_to_file_with_comments(
    config: dict, file_path: str, original_yaml_str: Optional[str] = None
):
    """Save configuration to file, preserving comments when possible."""
    if original_yaml_str:
        try:
            yaml_str, _warnings = merge_config_into_yaml(config, original_yaml_str)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(yaml_str)
            return
        except Exception as e:
            print(f"Warning: Could not preserve comments, using standard format: {e}")

    stone_config = convert_to_stone_format(config)
    yaml_str = yaml_to_string_with_comments(stone_config)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_str)


def _update_yaml_preserving_comments(original_data, new_data, default_props_by_id=None):
    """Merge *new_data* into *original_data* in-place, preserving ruamel comments.

    Mutates *original_data* directly so that ``.ca`` comment metadata attached
    to the ``CommentedMap`` container survives (rebuilding a new container would
    lose top-level / EOL / blank-line comments).

    Rules for dict merging:
    - Keys present in both: recurse for dicts/lists; replace scalar otherwise.
    - Keys only in *new_data*: added to *original_data*.
    - Keys only in *original_data*: **left unchanged** (not removed).
      Top-level passthrough keys (``metadata``, ``phases``, ``sweeps``, …)
      must survive across merge cycles.

    *default_props_by_id* is forwarded to array merges so that normalization-
    injected properties on existing nodes are not polluted into the YAML.
    """
    from ruamel.yaml.comments import CommentedSeq  # noqa: F401

    if not isinstance(original_data, dict) or not isinstance(new_data, dict):
        return new_data

    for key, new_value in new_data.items():
        if key in original_data:
            original_value = original_data[key]
            if isinstance(original_value, dict) and isinstance(new_value, dict):
                _update_yaml_preserving_comments(original_value, new_value)
            elif isinstance(original_value, (list, CommentedSeq)) and isinstance(
                new_value, list
            ):
                _update_yaml_array_preserving_comments(
                    original_data,
                    key,
                    new_value,
                    default_props_by_id=default_props_by_id,
                )
            else:
                original_data[key] = new_value
        else:
            original_data[key] = new_value

    return original_data


def _update_yaml_array_preserving_comments(
    parent_map, array_key, new_array, default_props_by_id=None
):
    """Replace the list at *parent_map[array_key]* with items from *new_array*.

    Items are matched by their ``id`` field.  For matched items, the original
    entry is mutated in-place via :func:`_update_yaml_item_preserving_comments`.
    Items in the original not present in *new_array* are dropped.
    New items (GUI-added) not in the original are appended at the end.
    Original ordering is preserved for existing items.

    Mutating in-place (rather than rebuilding the ``CommentedSeq``) keeps
    ruamel's sequence-level ``.ca`` comment metadata intact.

    *default_props_by_id* is forwarded to the item merge so normalization-
    injected properties are not written into items that didn't have them.
    """
    from ruamel.yaml.comments import CommentedSeq

    original_array = parent_map[array_key]

    original_by_id = {}
    for item in original_array:
        if isinstance(item, dict) and "id" in item:
            original_by_id[item["id"]] = item

    new_by_id = {}
    for new_item in new_array:
        if isinstance(new_item, dict) and "id" in new_item:
            new_by_id[new_item["id"]] = new_item

    # Build the new sequence preserving original ordering for existing items,
    # then appending new (GUI-added) items at the end.
    new_items = []
    for orig_item in original_array:
        if isinstance(orig_item, dict) and "id" in orig_item:
            item_id = orig_item["id"]
            if item_id in new_by_id:
                injected = (default_props_by_id or {}).get(item_id)
                merged = _update_yaml_item_preserving_comments(
                    orig_item, new_by_id[item_id], injected_props=injected
                )
                new_items.append(merged)
            # If item_id not in new_by_id, the item was removed — skip it.
        else:
            new_items.append(orig_item)
    # Append GUI-added items (those not in the original).
    for new_item in new_array:
        if isinstance(new_item, dict) and "id" in new_item:
            if new_item["id"] not in original_by_id:
                new_items.append(new_item)
        elif new_item not in new_items:
            new_items.append(new_item)

    if isinstance(original_array, CommentedSeq):
        # Mutate the existing CommentedSeq in-place so .ca survives.
        original_array.clear()
        for item in new_items:
            original_array.append(item)
    else:
        parent_map[array_key] = new_items


def _update_yaml_item_preserving_comments(original_item, new_item, injected_props=None):
    """Merge *new_item* into the original STONE network/stage list item.

    Handles STONE v2 shape where items look like::

        {id: ..., <KindKey>: {prop1: v1, ...}, source: ..., target: ...}

    - **Kind-key change**: if ``new_item`` has a different component-type key
      (e.g. ``IdealGasConstPressureReactor`` instead of ``IdealGasReactor``),
      the old kind key is removed and the new one is added.
    - **New properties**: keys present only in ``new_item`` that are not
      normalization-injected defaults are added to the component property dict.
    - **Property deletion**: keys present in the original component property dict
      but absent from the new one are deleted (propagates GUI property removal).
    - **In-place mutation**: ``original_item`` (a ``CommentedMap``) is mutated
      directly so ``.ca`` comment metadata survives.

    *injected_props* is a ``{key: value}`` dict of properties that a fresh
    normalize of the original YAML would inject automatically.  New properties
    matching these are skipped to avoid polluting the YAML.
    """
    if not isinstance(original_item, dict) or not isinstance(new_item, dict):
        return new_item

    # Identify the component-type key in each item (the key whose value is a
    # dict of properties, i.e. not id/source/target/metadata/etc.).
    _NON_KIND_KEYS = {
        "id",
        "source",
        "target",
        "metadata",
        "mechanism",
        "description",
        "label",
        "mechanism_switch",
        "group",
        "mass_flow_rate",
    }

    def _kind_key(item):
        for k, v in item.items():
            if k not in _NON_KIND_KEYS and isinstance(v, dict):
                return k
        return None

    orig_kind = _kind_key(original_item)
    new_kind = _kind_key(new_item)

    # -- Handle kind-key change --
    if orig_kind and new_kind and orig_kind != new_kind:
        # Remove old kind key; the new one will be added below.
        del original_item[orig_kind]

    # -- Merge all keys from new_item into original_item --
    for key, new_value in new_item.items():
        if key == orig_kind and new_kind and orig_kind != new_kind:
            continue  # already removed above

        if key in original_item:
            original_value = original_item[key]
            if (
                key == (new_kind or orig_kind)
                and isinstance(original_value, dict)
                and isinstance(new_value, dict)
            ):
                # Property dict: merge and delete removed keys.
                _merge_property_dict_inplace(original_value, new_value, injected_props)
            elif isinstance(original_value, dict) and isinstance(new_value, dict):
                _update_yaml_preserving_comments(original_value, new_value)
            else:
                original_item[key] = new_value
        else:
            original_item[key] = new_value

    return original_item


def _merge_property_dict_inplace(original_props, new_props, injected_props=None):
    """Merge *new_props* into *original_props* in-place.

    Rules:
    - Keys present in *original_props* that are absent from *new_props*:
      deleted (propagates GUI property removal).
    - Keys present in both: updated in-place.
    - Keys only in *new_props* (not in original):
      - If they also appear in *injected_props* with the same value:
        they are normalization artifacts (e.g. ``pressure`` injected by
        ``propagate_terminal_pressure_defaults``) → **skip**.
      - Otherwise they were explicitly set by the user in the GUI → **add**.

    *injected_props* is an optional dict of ``{prop_key: value}`` for
    properties that a fresh normalize of the original YAML would produce
    automatically.  Pass ``None`` to skip injection-filtering (all new
    keys are added).

    Depth is limited to the component property block (one level down from the
    kind key), not the full document.
    """
    injected = injected_props or {}

    # Delete keys removed by the GUI.
    keys_to_delete = [k for k in original_props if k not in new_props]
    for k in keys_to_delete:
        del original_props[k]

    # Add/update keys.
    for k, v in new_props.items():
        if k in original_props:
            old_v = original_props[k]
            if isinstance(old_v, dict) and isinstance(v, dict):
                _update_yaml_preserving_comments(old_v, v)
            else:
                original_props[k] = v
        elif k in injected and injected[k] == v:
            # Normalization-injected default — do not pollute the YAML.
            pass
        else:
            # Explicitly set by the user via the GUI → add it.
            original_props[k] = v


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
