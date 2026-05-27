"""Staged solving of Boulder reactor networks.

When a STONE YAML declares a top-level ``groups`` section, each group
represents an independent sub-network (stage) that is solved sequentially.
Stages are connected by *inter-stage connections* whose ``mechanism_switch``
block triggers species mapping when the two groups use different kinetic
mechanisms.

Public API
----------
- :func:`build_stage_graph`       – parse config, return a :class:`StageExecutionPlan`
- :func:`synthesize_stream_points` – return node/connection dicts for all stream-point reservoirs
- :func:`solve_staged`            – execute the plan, return a
  :class:`~boulder.lagrangian.LagrangianTrajectory`

Architecture (with stream_reservoirs enabled)
---------------------------------------------
1. ``build_stage_graph`` partitions nodes/connections by group, topologically
   sorts the stages, and validates acyclicity.  Each :class:`InterStageConnection`
   is assigned a ``stream_point_id`` (``"{source_node}_outlet"``) that will become a
   ``ct.Reservoir`` at the stage boundary — a P&ID *stream point* (diamond node).
2. ``solve_staged`` iterates in order:
   a. Build a sub-ReactorNet for the stage including:
      - downstream-side inlet MFCs from the stream-point reservoirs declared in
        ``stage.inter_connections_in``.
   b. Solve the sub-network.
   c. Extract outlet state(s) and write them into the stream-point reservoirs
      (applying ``mechanism_switch`` when declared).
   d. Record states in the trajectory.
3. After all stages: build a single visualization ReactorNet from all converged
   reactor states with all connections (including inter-stage) restored.

Legacy mode (``stream_reservoirs=False``)
-----------------------------------------
When the flag is off, behaviour is identical to the pre-2026 implementation:
the inter-stage MFC is virtual and the upstream outlet state is copied directly
onto the downstream ``reactor.phase.TPY`` via ``inlet_states``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import cantera as ct
import numpy as np

if TYPE_CHECKING:
    from .cantera_converter import DualCanteraConverter
    from .lagrangian import LagrangianTrajectory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class InterStageConnection:
    """A connection that crosses stage (group) boundaries.

    When ``stream_reservoirs=True`` (default in new runs), each instance
    contributes to exactly one ``ct.Reservoir`` named ``stream_point_id``
    (one per source node, shared across all downstream targets).  The reservoir
    holds the converged stream state (T, P, Y) after the upstream solve, with
    ``mechanism_switch`` applied when present.  A separate inlet MFC is built
    per downstream target.

    Legacy mode (``stream_reservoirs=False``): the connection remains virtual
    – the upstream outlet state is copied directly to ``reactor.phase.TPY`` via
    ``inlet_states``, matching pre-2026 behaviour.

    The connection is always *restored* in the final visualization ReactorNet so
    the full topology is visible in ``ReactorNet.draw()`` and Sankey diagrams.
    """

    id: str
    source_node: str
    target_node: str
    source_stage: str
    target_stage: str
    conn_type: str = "MassFlowController"
    properties: Dict[str, Any] = field(default_factory=dict)
    #: Optional ``{htol: ..., Xtol: ...}`` block; triggers species mapping.
    mechanism_switch: Optional[Dict[str, Any]] = None

    @property
    def stream_point_id(self) -> str:
        """Deterministic id for the synthesised stream-point :class:`~cantera.Reservoir`.

        One reservoir is created *per source node* (not per connection), so all
        inter-stage connections that share a source node map to the same id.
        """
        return f"{self.source_node}_outlet"

    @property
    def inlet_mfc_id(self) -> str:
        """Id for the downstream-side MFC connecting stream-point reservoir to target."""
        return f"{self.source_node}_outlet_to_{self.target_node}"

    # ---------------------------------------------------------------------------
    # Backward-compatible aliases (kept for transition; remove after rename is stable)
    # ---------------------------------------------------------------------------

    @property
    def reservoir_id(self) -> str:
        """Deprecated alias for :attr:`stream_point_id`."""
        return self.stream_point_id

    @property
    def outlet_mfc_id(self) -> str:
        """Upstream-side MFC is no longer synthesised; this id is kept as a dead stub."""
        return f"{self.id}__stream_out"


@dataclass
class Stage:
    """A single group in the staged execution plan."""

    id: str
    mechanism: str
    #: Resolved solver configuration dict merged from ``settings.solver`` (global
    #: defaults) and ``groups.<id>.solver`` (stage overrides).  Always present after
    #: :func:`build_stage_graph`; keys mirror the STONE ``solver:`` block.
    solver: Dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Deprecated: kept for backward-compat; mapped into solver at parse time.
    # ---------------------------------------------------------------------------
    #: Legacy ``"advance_to_steady_state"`` or ``"advance"`` directive.
    solve_directive: str = "advance_to_steady_state"
    #: Legacy advance horizon in seconds; only used when *solve_directive* is ``"advance"``.
    advance_time: float = 1.0

    node_ids: List[str] = field(default_factory=list)
    intra_connections: List[Dict[str, Any]] = field(default_factory=list)
    inter_connections_in: List[InterStageConnection] = field(default_factory=list)
    inter_connections_out: List[InterStageConnection] = field(default_factory=list)


@dataclass
class StageExecutionPlan:
    """Topologically-sorted list of :class:`Stage` objects."""

    ordered_stages: List[Stage]
    all_inter_connections: List[InterStageConnection]
    #: ``{node_id: stage_id}`` for fast lookup.
    node_to_stage: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# build_stage_graph
# ---------------------------------------------------------------------------


def build_stage_graph(config: Dict[str, Any]) -> StageExecutionPlan:
    """Parse a normalized config and return a :class:`StageExecutionPlan`.

    Parameters
    ----------
    config :
        Normalized config dict (output of ``normalize_config()``) that contains
        a top-level ``groups`` key.

    Returns
    -------
    StageExecutionPlan

    Raises
    ------
    ValueError
        If a node references an unknown group, or if the stage graph has cycles.
    """
    groups_cfg: Dict[str, Any] = config.get("groups") or {}
    nodes: List[Dict[str, Any]] = config.get("nodes") or []
    connections: List[Dict[str, Any]] = config.get("connections") or []

    # Default mechanism from phases section
    default_mechanism = "gri30.yaml"
    phases = config.get("phases") or {}
    if isinstance(phases, dict):
        gas_phase = phases.get("gas") or {}
        if isinstance(gas_phase, dict):
            default_mechanism = gas_phase.get("mechanism", default_mechanism)

    # Global solver defaults from settings.solver (if any)
    global_solver_defaults: Dict[str, Any] = {}
    settings = config.get("settings") or {}
    if isinstance(settings, dict):
        raw_global = settings.get("solver")
        if isinstance(raw_global, dict):
            global_solver_defaults = dict(raw_global)

    # Build Stage objects from groups config
    stages: Dict[str, Stage] = {}
    for gid, gcfg in groups_cfg.items():
        gcfg = gcfg or {}

        # ---------- legacy shim: promote solve:/advance_time: into solver block ----------
        legacy_solve = gcfg.get("solve")
        legacy_advance_time = gcfg.get("advance_time")
        per_stage_solver: Dict[str, Any] = {}
        if isinstance(gcfg.get("solver"), dict):
            per_stage_solver = dict(gcfg["solver"])
        elif legacy_solve is not None:
            # Legacy form: translate to solver.kind (with deprecation handled in config.py)
            per_stage_solver["kind"] = str(legacy_solve)
            if legacy_advance_time is not None:
                from .utils import coerce_unit_string  # noqa: PLC0415

                at_si = coerce_unit_string(legacy_advance_time, "advance_time")
                per_stage_solver["advance_time"] = float(at_si)

        # Merge: global defaults → per-stage overrides
        resolved_solver: Dict[str, Any] = {**global_solver_defaults, **per_stage_solver}

        # Derive legacy fields from resolved solver for backward-compat consumers
        solve_directive = str(resolved_solver.get("kind", "advance_to_steady_state"))
        advance_time_val = float(resolved_solver.get("advance_time", 1.0))

        stages[gid] = Stage(
            id=gid,
            mechanism=str(gcfg.get("mechanism", default_mechanism)),
            solver=resolved_solver,
            solve_directive=solve_directive,
            advance_time=advance_time_val,
        )

    # Map each node to its stage via node.properties.group
    node_to_stage: Dict[str, str] = {}
    for node in nodes:
        nid = node["id"]
        props = node.get("properties") or {}
        # Support group at node top-level OR inside properties
        group = node.get("group") or props.get("group") or ""
        if group:
            if group not in stages:
                raise ValueError(
                    f"Node '{nid}' references unknown group '{group}'. "
                    f"Available groups: {list(stages.keys())}"
                )
            stages[group].node_ids.append(nid)
            node_to_stage[nid] = group
        # Nodes without a group are excluded from staged solving

    # Partition connections into intra-stage and inter-stage
    inter_connections: List[InterStageConnection] = []
    for conn in connections:
        cid = conn["id"]
        src = conn["source"]
        tgt = conn["target"]
        src_stage = node_to_stage.get(src)
        tgt_stage = node_to_stage.get(tgt)

        if src_stage is not None and tgt_stage is not None and src_stage != tgt_stage:
            # Inter-stage connection
            ic = InterStageConnection(
                id=cid,
                source_node=src,
                target_node=tgt,
                source_stage=src_stage,
                target_stage=tgt_stage,
                conn_type=conn.get("type", "MassFlowController"),
                properties=dict(conn.get("properties") or {}),
                mechanism_switch=conn.get("mechanism_switch"),
            )
            inter_connections.append(ic)
            stages[src_stage].inter_connections_out.append(ic)
            stages[tgt_stage].inter_connections_in.append(ic)

        elif src_stage is not None and src_stage == tgt_stage:
            # Intra-stage connection
            stages[src_stage].intra_connections.append(conn)
        # else: connection spans ungrouped nodes – passed through unchanged

    # Topological sort
    ordered = _topological_sort(stages)

    return StageExecutionPlan(
        ordered_stages=ordered,
        all_inter_connections=inter_connections,
        node_to_stage=node_to_stage,
    )


def _topological_sort(stages: Dict[str, Stage]) -> List[Stage]:
    """Kahn's algorithm on the stage dependency graph.

    Raises
    ------
    ValueError
        If cycles are detected.
    """
    in_degree: Dict[str, int] = {sid: 0 for sid in stages}
    adjacency: Dict[str, List[str]] = {sid: [] for sid in stages}

    for sid, stage in stages.items():
        for ic in stage.inter_connections_out:
            tgt = ic.target_stage
            if tgt in adjacency[sid]:
                continue  # skip duplicate edges
            adjacency[sid].append(tgt)
            in_degree[tgt] += 1

    queue = sorted(sid for sid, deg in in_degree.items() if deg == 0)
    result: List[Stage] = []

    while queue:
        sid = queue.pop(0)
        result.append(stages[sid])
        for downstream in adjacency[sid]:
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                queue.append(downstream)
                queue.sort()  # deterministic ordering for stages at the same depth

    if len(result) != len(stages):
        cycle_nodes = [sid for sid, deg in in_degree.items() if deg > 0]
        raise ValueError(
            f"Stage dependency graph has cycles involving: {cycle_nodes}. "
            "Cyclic reactor networks are not supported in staged mode. "
            "Remove cyclic inter-stage connections or use a single ReactorNet."
        )

    return result


# ---------------------------------------------------------------------------
# synthesize_stream_points
# ---------------------------------------------------------------------------


def synthesize_stream_points(
    plan: StageExecutionPlan,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return synthetic node and connection dicts for all stream-point reservoirs.

    One :class:`~cantera.Reservoir` (P&ID *stream point*, rendered as a diamond)
    is created **per source node** across all inter-stage connections.  When a
    single source feeds multiple downstream stages, one shared reservoir is used
    and each downstream gets its own inlet MFC.

    The reservoir is used **only in the downstream stage** as an inlet boundary
    condition.  It holds the converged upstream outlet state (T, P, Y) written
    after the upstream solve — see :func:`solve_staged`.

    Only one MFC is synthesised per (source, target) pair: the inlet MFC from
    the stream-point reservoir to the target reactor in the downstream stage.  No
    outlet MFC is built in the upstream stage; this avoids the stale-reference
    problem that arises when the placeholder reservoir is replaced after the
    upstream solve.

    The returned dicts follow the same normalized schema as regular nodes and
    connections so they can be injected directly into ``build_sub_network``.

    Parameters
    ----------
    plan :
        Execution plan produced by :func:`build_stage_graph`.

    Returns
    -------
    (nodes, connections)
        ``nodes`` – one ``Reservoir`` dict per *source node* (not per connection).
        ``connections`` – one ``MassFlowController`` dict per inter-stage
        connection (inlet side only, group = target stage).  ``mass_flow_rate``
        is copied from ``ic.properties`` when explicitly declared.
    """
    nodes: List[Dict[str, Any]] = []
    connections: List[Dict[str, Any]] = []

    # Group by source node to produce ONE stream-point diamond per source.
    from collections import defaultdict  # noqa: PLC0415

    by_source: Dict[str, List[InterStageConnection]] = defaultdict(list)
    for ic in plan.all_inter_connections:
        by_source[ic.source_node].append(ic)

    seen_stream_ids: set = set()

    for source_node, ics in by_source.items():
        # Use the first IC to pull stage metadata (all ICs share the same source).
        representative = ics[0]
        stream_id = representative.stream_point_id  # "{source_node}_outlet"

        if stream_id not in seen_stream_ids:
            seen_stream_ids.add(stream_id)
            # Stream-point Reservoir node — placeholder state replaced after upstream solve.
            nodes.append(
                {
                    "id": stream_id,
                    "type": "Reservoir",
                    "properties": {
                        "temperature": 300.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "stream_point": True,
                        "upstream_stage": representative.source_stage,
                        "source_node": source_node,
                        # target_node: list all downstream nodes for metadata
                        "target_nodes": [ic.target_node for ic in ics],
                    },
                    "metadata": {
                        "stream_point": True,
                        "upstream_stage": representative.source_stage,
                        "source_node": source_node,
                        "target_nodes": [ic.target_node for ic in ics],
                        "original_connection_ids": [ic.id for ic in ics],
                    },
                }
            )

        # One inlet MFC per downstream target
        for ic in ics:
            mdot = ic.properties.get("mass_flow_rate")
            in_props: Dict[str, Any] = {}
            if mdot is not None:
                in_props["mass_flow_rate"] = mdot

            connections.append(
                {
                    "id": ic.inlet_mfc_id,  # "{source_node}_outlet_to_{target_node}"
                    "type": "MassFlowController",
                    "source": stream_id,
                    "target": ic.target_node,
                    "properties": in_props,
                    "metadata": {"stream_point": True, "side": "inlet"},
                    "group": ic.target_stage,
                }
            )

    return nodes, connections


# Backward-compatible alias for external callers and tests that import the old name.
synthesize_interface_nodes = synthesize_stream_points


# ---------------------------------------------------------------------------
# solve_staged
# ---------------------------------------------------------------------------


def solve_staged(
    converter: "DualCanteraConverter",
    plan: StageExecutionPlan,
    config: Dict[str, Any],
    progress_callback: Optional[Callable] = None,
    stream_reservoirs: bool = True,
    # Backward-compatible alias
    interface_reservoirs: Optional[bool] = None,
) -> "LagrangianTrajectory":
    """Execute a :class:`StageExecutionPlan` sequentially.

    For each stage:

    1. Filter nodes/connections for this stage.
    2. Synthesise stream-point reservoirs and build real MFCs on the downstream
       side of each stage boundary (see :func:`synthesize_stream_points`).
    3. Build stage sub-ReactorNet.
    4. Solve according to ``stage.solve_directive``.
    5. Extract outlet state(s), apply ``mechanism_switch`` if present, and
       write the result into the stream-point reservoir.
    6. Append states to the Lagrangian trajectory.

    After all stages: build visualization ReactorNet from all converged states.

    Parameters
    ----------
    converter :
        A :class:`~boulder.cantera_converter.DualCanteraConverter` instance
        (plugins, gas cache, and reactor registry live here).
    plan :
        Execution plan from :func:`build_stage_graph`.
    config :
        Normalized config (used to locate all nodes/connections for viz network).
    progress_callback :
        Optional callable ``(stage_id, n_done, n_total) -> None``.
    stream_reservoirs :
        When ``True`` (default), synthesise a ``ct.Reservoir`` (P&ID
        stream-point diamond) for every source node with inter-stage
        connections.  Pass ``False`` only in tests exercising the legacy path.
    interface_reservoirs :
        Deprecated alias for *stream_reservoirs*.  Ignored when *stream_reservoirs*
        is also passed.  Will be removed in a future version.

    Returns
    -------
    LagrangianTrajectory
    """
    # Honor the deprecated alias so callers that still pass interface_reservoirs= work.
    if interface_reservoirs is not None and not stream_reservoirs:
        stream_reservoirs = interface_reservoirs

    from .lagrangian import LagrangianTrajectory

    trajectory = LagrangianTrajectory()

    # ``inlet_states[node_id]`` holds the ct.Solution ready to initialise the
    # downstream reactor.  In legacy mode this is the primary handoff mechanism.
    # In stream_reservoirs mode it is kept as an inspection snapshot only.
    inlet_states: Dict[str, ct.Solution] = {}

    # Pre-build all stream-point reservoirs and associated connection dicts once
    # so both upstream and downstream stage builds can reference them.
    stream_node_dicts: Dict[str, Dict[str, Any]] = {}  # stream_point_id -> node dict
    stream_conns_by_stage: Dict[
        str, List[Dict[str, Any]]
    ] = {}  # stage_id -> conn dicts
    if stream_reservoirs:
        stream_nodes, stream_conns = synthesize_stream_points(plan)
        for nd in stream_nodes:
            stream_node_dicts[nd["id"]] = nd
        for cd in stream_conns:
            grp = cd.get("group", "")
            stream_conns_by_stage.setdefault(grp, []).append(cd)

    n_stages = len(plan.ordered_stages)

    for stage_idx, stage in enumerate(plan.ordered_stages):
        logger.info(
            "Staged solve: stage '%s' (%d/%d, %d reactors)",
            stage.id,
            stage_idx + 1,
            n_stages,
            len(stage.node_ids),
        )

        # Filter nodes that belong to this stage
        stage_node_ids = set(stage.node_ids)
        stage_nodes = [
            n for n in (config.get("nodes") or []) if n["id"] in stage_node_ids
        ]

        # Augment with stream-point reservoir nodes and inlet MFCs for incoming
        # inter-stage connections.  The reservoir is created only once (in the
        # downstream stage), populated with the converged upstream state before
        # build_sub_network is called for that stage.
        extra_nodes: List[Dict[str, Any]] = []
        extra_conns: List[Dict[str, Any]] = []
        if stream_reservoirs:
            # Only include reservoirs on the INLET (downstream) side.
            # The upstream stage does NOT get an outlet MFC to the stream-point reservoir
            # — this avoids the stale-reference collision in the viz network.
            seen_stream_ids: set = set()
            for ic in stage.inter_connections_in:
                nd = stream_node_dicts.get(ic.stream_point_id)
                if nd is not None and ic.stream_point_id not in seen_stream_ids:
                    seen_stream_ids.add(ic.stream_point_id)
                    extra_nodes.append(nd)
            extra_conns = stream_conns_by_stage.get(stage.id, [])

        # Merge intra-stage connections with interface MFCs for this stage
        stage_connections = list(stage.intra_connections) + extra_conns

        # Build sub-network and solve
        network, stage_reactors = converter.build_sub_network(
            stage_nodes=stage_nodes + extra_nodes,
            stage_connections=stage_connections,
            stage_mechanism=stage.mechanism,
            inlet_states=inlet_states,
            stage_id=stage.id,
            stage=stage,
        )
        trajectory.networks[stage.id] = network

        # Apply causal-layer bindings (Phase B): wire signals to MFCs / reactors.
        _signals_block = config.get("signals")
        _bindings_block = config.get("bindings")
        if _signals_block and _bindings_block:
            from boulder.bindings import apply_bindings_block
            from boulder.signals import build_signal_registry

            _signal_registry = build_signal_registry(_signals_block)
            apply_bindings_block(converter, _bindings_block, _signal_registry)

        # Collect SolutionArray in flow order through the stage
        flow_order = _flow_order_within_stage(stage)
        states = _collect_stage_states(
            stage, stage_reactors, flow_order, converter, network=network
        )
        mapping_losses: Optional[Dict[str, float]] = None

        # Extract outlet states for each outgoing inter-stage connection
        for ic in stage.inter_connections_out:
            source_reactor = stage_reactors.get(ic.source_node)
            if source_reactor is None:
                logger.warning(
                    "Inter-stage connection '%s': source reactor '%s' not found.",
                    ic.id,
                    ic.source_node,
                )
                continue

            # Copy outlet state into a fresh Solution at the stage mechanism
            outlet_gas = _extract_gas_state(source_reactor, stage.mechanism, converter)

            # Apply mechanism switch if requested
            if ic.mechanism_switch is not None:
                target_stage = next(
                    (s for s in plan.ordered_stages if s.id == ic.target_stage), None
                )
                if target_stage is None:
                    raise ValueError(
                        f"Inter-stage connection '{ic.id}' targets unknown stage "
                        f"'{ic.target_stage}'."
                    )
                outlet_gas, losses = _apply_mechanism_switch(
                    outlet_gas,
                    target_stage.mechanism,
                    ic.mechanism_switch,
                    converter,
                )
                mapping_losses = losses

            if stream_reservoirs:
                _update_stream_point(
                    ic,
                    outlet_gas,
                    stage.mechanism,
                    converter,
                    stream_conns_by_stage.get(ic.target_stage, []),
                    stage_intra_connections=list(stage.intra_connections),
                )
                # Back-fill the node dict with converged state so _sync_streams_into_config
                # ships the full P&ID stream data to the frontend without a new API call.
                stream_id = ic.stream_point_id
                nd = stream_node_dicts.get(stream_id)
                if nd is not None:
                    meta = converter.reactor_meta.get(stream_id) or {}
                    nd_props = nd.setdefault("properties", {})
                    nd_props["temperature"] = float(outlet_gas.T)
                    nd_props["pressure"] = float(outlet_gas.P)
                    nd_props["mdot"] = meta.get("mdot", 0.0)
                    nd_props["density"] = meta.get("density", 0.0)
                    nd_props["h_mass"] = meta.get("h_mass", 0.0)
                    nd_props["v_dot_normal_m3_h"] = (
                        meta.get("v_dot_normal_m3_s", 0.0) * 3600.0
                    )
                    nd_props["v_dot_real_m3_h"] = (
                        meta.get("v_dot_real_m3_s", 0.0) * 3600.0
                    )
                    nd_props["top_Y"] = meta.get("top_Y", {})
                    nd_props["composition"] = ",".join(
                        f"{sp}:{y:.4f}" for sp, y in (meta.get("top_Y") or {}).items()
                    )
            else:
                # Legacy: direct state copy to downstream reactor initialisation
                inlet_states[ic.target_node] = outlet_gas

            # Always keep inlet_states updated as an inspection snapshot
            inlet_states[ic.target_node] = outlet_gas

        trajectory.add_segment(
            stage_id=stage.id,
            mechanism=stage.mechanism,
            states=states,
            mapping_losses=mapping_losses,
        )

        logger.info(
            "Staged solve: stage '%s' finished (%d/%d)",
            stage.id,
            stage_idx + 1,
            n_stages,
        )

        if progress_callback is not None:
            try:
                progress_callback(stage.id, stage_idx + 1, n_stages)
            except Exception:
                pass

    # Build visualization ReactorNet from all converged states.
    # When stream_reservoirs is True, the original inter-stage connection IDs
    # (e.g. "psr_to_pfr") are passed as already-built so build_viz_network does
    # not create a direct source→target MFC that bypasses the stream-point reservoir.
    # The stream-point reservoir and its inlet MFC are already in converter.connections.
    already_built = set(converter.connections.keys()) | set(converter.walls.keys())
    if stream_reservoirs:
        for ic in plan.all_inter_connections:
            already_built.add(ic.id)

    # Assemble all_connections including virtual source→stream_point MFCs.
    # Without these virtual MFCs the viz ReactorNet (and thus the Network tab
    # and Sankey generator) would see two disconnected subgraphs: one for the
    # upstream stage (source reactor alone) and one for the downstream stages
    # (stream-point reservoir → target reactor).  The virtual MFC makes the
    # topology fully connected and carries the correct mass flow rate.
    all_connections = list(config.get("connections") or [])
    if stream_reservoirs:
        for nid, meta in converter.reactor_meta.items():
            if not meta.get("stream_point"):
                continue
            source_id = meta.get("source_node")
            mdot = float(meta.get("mdot") or 0.0)
            if (
                source_id
                and source_id in converter.reactors
                and nid in converter.reactors
            ):
                virt_id = f"_viz_{source_id}_to_{nid}"
                all_connections.append(
                    {
                        "id": virt_id,
                        "type": "MassFlowController",
                        "source": source_id,
                        "target": nid,
                        "properties": {"mass_flow_rate": mdot},
                        "metadata": {"virtual": True},
                    }
                )

    logger.info("Staged solve complete – building visualization ReactorNet.")
    viz_net = converter.build_viz_network(
        all_connections=all_connections,
        built_conn_ids=already_built,
    )
    trajectory.viz_network = viz_net

    if stream_reservoirs:
        _sync_streams_into_config(
            config, plan, stream_node_dicts, stream_conns_by_stage
        )

    return trajectory


# ---------------------------------------------------------------------------
# Helpers used by solve_staged
# ---------------------------------------------------------------------------


def _update_stream_point(
    ic: "InterStageConnection",
    outlet_gas: Any,
    mechanism: str,
    converter: Any,
    stream_inlet_mfc_dicts: List[Dict[str, Any]],
    stage_intra_connections: Optional[List[Dict[str, Any]]] = None,
    display_gas: Optional[Any] = None,
) -> None:
    """Refresh the stream-point reservoir for *ic* with the converged upstream state.

    Cantera ``Reservoir`` objects are immutable after construction.  This helper
    builds a fresh one from *outlet_gas*, registers it on *converter*, propagates
    the measured outlet mass-flow-rate into the matching inlet MFC dict, and
    stores derived thermo properties (Y, H, h_mass, density, mdot) on the
    stream-point node dict so the PropertiesPanel receives a full P&ID stream view
    without a separate API call.

    Parameters
    ----------
    outlet_gas :
        Converged gas in the **target** mechanism (post mechanism-switch when
        applicable).  Used to build the Cantera ``Reservoir`` so downstream
        reactors can read it in their own species basis.
    mechanism :
        Mechanism string corresponding to *outlet_gas* (target mechanism when
        a switch occurred, source mechanism otherwise).
    display_gas :
        Optional gas in the **source** mechanism.  When provided, P&ID display
        properties (T, P, composition, density, h_mass, etc.) are derived from
        this object instead of *outlet_gas*.  Use this when a mechanism switch
        has been applied and the pre-switch composition is more meaningful for
        the operator (more species, richer composition).  When ``None``,
        *outlet_gas* is used for both the Cantera object and display.
    stage_intra_connections :
        Intra-stage connection dicts for the source stage.  Passed to
        :func:`_measure_outlet_mdot` as a fallback for plugin-built reactors
        that do not register a standard ``ct.MassFlowController`` in
        ``converter.connections``.
    """
    props_gas = display_gas if display_gas is not None else outlet_gas
    stream_id = ic.stream_point_id
    new_res_gas = converter._get_gas_for_mech(mechanism)
    new_res_gas.TPY = outlet_gas.T, outlet_gas.P, outlet_gas.Y
    new_stream_res = ct.Reservoir(new_res_gas, clone=False)
    new_stream_res.name = stream_id
    converter.reactors[stream_id] = new_stream_res

    outlet_mdot = _measure_outlet_mdot(
        ic.source_node,
        converter,
        stage_intra_connections=stage_intra_connections,
    )
    logger.debug(
        "Stream-point '%s' mdot=%.4g kg/s (source=%s, n_conns=%d)",
        stream_id,
        outlet_mdot,
        ic.source_node,
        len(converter.connections),
    )

    # Compute derived thermo for the stream-point from the converged gas state.
    # Use props_gas (pre-switch if a switch occurred) for the P&ID display so
    # the operator sees the source-mechanism composition (richer species).
    try:
        T_norm = 273.15  # Normal conditions reference temperature [K]
        P_norm = 101325.0  # Normal conditions reference pressure [Pa]
        rho = float(props_gas.density)
        h_mass = float(props_gas.enthalpy_mass)
        h_molar = float(props_gas.enthalpy_mole)
        # Normal volumetric flow [Nm³/s]: mdot / (ρ at normal conditions)
        props_mech = props_gas.source if hasattr(props_gas, "source") else mechanism
        norm_gas = converter._get_gas_for_mech(props_mech)
        norm_gas.TPY = T_norm, P_norm, props_gas.Y
        rho_norm = float(norm_gas.density)
        v_dot_norm = outlet_mdot / rho_norm if rho_norm > 0 else 0.0
        v_dot_real = outlet_mdot / rho if rho > 0 else 0.0
        # Top-3 species by mass fraction
        Y = {sp: float(props_gas.Y[i]) for i, sp in enumerate(props_gas.species_names)}
        top_Y = dict(sorted(Y.items(), key=lambda kv: kv[1], reverse=True)[:3])
    except Exception:
        rho = h_mass = h_molar = v_dot_norm = v_dot_real = 0.0
        top_Y = {}

    converter.reactor_meta.setdefault(stream_id, {}).update(
        {
            "mechanism": mechanism,
            "gas_solution": new_res_gas,
            "stream_point": True,
            "upstream_stage": ic.source_stage,
            "downstream_stage": ic.target_stage,
            "source_node": ic.source_node,
            "target_node": ic.target_node,
            "mdot": outlet_mdot,
            "density": rho,
            "h_mass": h_mass,
            "h_molar": h_molar,
            "v_dot_normal_m3_s": v_dot_norm,
            "v_dot_real_m3_s": v_dot_real,
            "top_Y": top_Y,
        }
    )

    # Propagate mdot into ALL inlet MFC dicts that draw from this stream-point
    # (fan-out: multiple downstreams may pull from the same reservoir).
    for cd in stream_inlet_mfc_dicts:
        if cd.get("source") == stream_id or cd["id"] == ic.inlet_mfc_id:
            cd.setdefault("properties", {})["mass_flow_rate"] = outlet_mdot

    logger.debug(
        "Stream-point reservoir '%s' updated: T=%.1f K, mdot=%.4g kg/s",
        stream_id,
        props_gas.T,
        outlet_mdot,
    )


# Backward-compatible alias
_update_iface_reservoir = _update_stream_point


def _sync_streams_into_config(
    config: Dict[str, Any],
    plan: "StageExecutionPlan",
    stream_node_dicts: Dict[str, Dict[str, Any]],
    stream_conns_by_stage: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Replace original inter-stage connection dicts with stream-point reservoir + inlet MFC.

    Mutates *config* in place so that ``config["nodes"]`` and
    ``config["connections"]`` reflect the actual post-solve Cantera topology:

    - Original inter-stage connection dicts (e.g. ``torch_to_psr``) are removed.
    - Stream-point reservoir node dicts are appended to ``config["nodes"]``.
    - One ``StreamConnector`` display edge ``{source} → {stream_point}`` per source
      is appended so the graph is visually connected (no Cantera object; frontend only).
    - Inlet MFC dicts (stream-point reservoir → target reactor) are appended to
      ``config["connections"]``.

    This is the single authoritative sync operation; both :func:`solve_staged`
    and :meth:`BoulderRunner.build` call it instead of duplicating the logic.
    """
    replaced_conn_ids = {ic.id for ic in plan.all_inter_connections}
    config["connections"] = [
        c for c in (config.get("connections") or []) if c["id"] not in replaced_conn_ids
    ]
    existing_node_ids = {n["id"] for n in (config.get("nodes") or [])}
    existing_conn_ids = {c["id"] for c in config["connections"]}
    config.setdefault("nodes", [])
    for nd in stream_node_dicts.values():
        if nd["id"] not in existing_node_ids:
            # Merge any derived thermo stored on the node dict back into properties
            # so the frontend PropertiesPanel sees all stream data in one payload.
            nd_copy = dict(nd)
            nd_copy["properties"] = dict(nd.get("properties") or {})
            config["nodes"].append(nd_copy)
        else:
            # Update existing node's properties with derived thermo (T, P, Y, mdot, …)
            for existing_nd in config["nodes"]:
                if existing_nd["id"] == nd["id"]:
                    existing_nd.setdefault("properties", {}).update(
                        nd.get("properties") or {}
                    )
                    break

    # Add one display-only "StreamConnector" edge per source node so the graph
    # shows a continuous chain:  source_reactor → stream_point → target_reactor.
    # This edge has no Cantera object; it is purely visual.
    seen_connector_sources: set = set()
    for ic in plan.all_inter_connections:
        stream_id = ic.stream_point_id
        source_id = ic.source_node
        connector_id = f"{source_id}_to_{stream_id}"
        if (
            source_id not in seen_connector_sources
            and connector_id not in existing_conn_ids
        ):
            seen_connector_sources.add(source_id)
            config["connections"].append(
                {
                    "id": connector_id,
                    "type": "StreamConnector",
                    "source": source_id,
                    "target": stream_id,
                    "properties": {},
                    "metadata": {"stream_point": True, "side": "outlet_connector"},
                }
            )
            existing_conn_ids.add(connector_id)

    for ic in plan.all_inter_connections:
        for cd in stream_conns_by_stage.get(ic.target_stage, []):
            if cd["id"] == ic.inlet_mfc_id:
                if cd["id"] not in existing_conn_ids:
                    config["connections"].append(cd)
                else:
                    # Update mdot on a placeholder connection added by preseed.
                    new_mdot = (cd.get("properties") or {}).get("mass_flow_rate")
                    if new_mdot is not None and new_mdot > 0:
                        for existing_cd in config["connections"]:
                            if existing_cd["id"] == cd["id"]:
                                existing_cd.setdefault("properties", {})[
                                    "mass_flow_rate"
                                ] = new_mdot
                                break


# Backward-compatible alias
_sync_iface_into_config = _sync_streams_into_config


def _measure_outlet_mdot(
    source_node_id: str,
    converter: Any,
    stage_intra_connections: Optional[List[Dict[str, Any]]] = None,
) -> float:
    """Return the total outlet mass flow rate [kg/s] of *source_node_id*.

    Strategy (in order of precedence):

    1. Sum ``ct.MassFlowController`` outlets from ``converter.connections``
       where ``upstream.name == source_node_id``.
    2. Fall back to inlet MFCs (``downstream.name == source_node_id``) — at
       steady state, mass-in = mass-out.
    3. If Cantera objects are not available (e.g. plugin-built composite reactors
       that do not register a standard MFC), scan *stage_intra_connections* for
       a connection with ``target == source_node_id`` that carries a
       ``mass_flow_rate`` property.  This is the zero-Cantera-object fallback.

    Identity comparison (``is``) is attempted first; name comparison is used as
    a fallback for plugin-built composite reactors where the stored object may
    differ from the MFC's upstream/downstream reference.
    """
    source_reactor = converter.reactors.get(source_node_id)

    if source_reactor is not None:

        def _is_source(reactor_ref) -> bool:
            if reactor_ref is source_reactor:
                return True
            try:
                return reactor_ref.name == source_node_id
            except AttributeError:
                return False

        outlet_mdot = inlet_mdot = 0.0
        for conn in converter.connections.values():
            if not isinstance(conn, ct.MassFlowController):
                continue
            try:
                mdot = float(conn.mass_flow_rate)
                if _is_source(conn.upstream):
                    outlet_mdot += mdot
                elif _is_source(conn.downstream):
                    inlet_mdot += mdot
            except ct.CanteraError:
                pass

        cantera_mdot = outlet_mdot if outlet_mdot > 0.0 else inlet_mdot
        if cantera_mdot > 0.0:
            return cantera_mdot

    # Fallback: scan connection dicts for explicit mass_flow_rate targeting this node.
    if stage_intra_connections:
        fallback_mdot = 0.0
        for cd in stage_intra_connections:
            if cd.get("target") == source_node_id:
                props = cd.get("properties") or {}
                mfr = props.get("mass_flow_rate")
                if mfr is not None:
                    try:
                        fallback_mdot += float(mfr)
                    except (TypeError, ValueError):
                        pass
        if fallback_mdot > 0.0:
            return fallback_mdot

    return 0.0


def _flow_order_within_stage(stage: Stage) -> List[str]:
    """Topological sort of node IDs within a stage using intra-stage connections."""
    node_ids = list(stage.node_ids)
    node_set = set(node_ids)

    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}
    adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}

    for conn in stage.intra_connections:
        src = conn["source"]
        tgt = conn["target"]
        if src in node_set and tgt in node_set:
            adjacency[src].append(tgt)
            in_degree[tgt] += 1

    queue = [nid for nid in node_ids if in_degree[nid] == 0]
    result: List[str] = []

    while queue:
        nid = queue.pop(0)
        result.append(nid)
        for ds in adjacency.get(nid, []):
            in_degree[ds] -= 1
            if in_degree[ds] == 0:
                queue.append(ds)

    # Append any remaining nodes (cycles within stage, or isolated)
    for nid in node_ids:
        if nid not in result:
            result.append(nid)

    return result


def _collect_stage_states(
    stage: Stage,
    stage_reactors: Dict[str, ct.ReactorBase],
    flow_order: List[str],
    converter: "DualCanteraConverter",
    network: Optional[ct.ReactorNet] = None,
) -> ct.SolutionArray:
    """Collect per-reactor final states into a SolutionArray in flow order.

    Residence time is taken from ``converter.reactor_meta[rid]["t_res_s"]``
    when available (populated by a post-build hook in an external plugin).
    For CSTR chains the cells have volumes; residence time is approximated as
    ``volume * density / mass_flow_rate`` using the first available outgoing
    mass flow rate; if unknown, the field is ``NaN``.
    """
    # Resolve mechanism and create template
    mech = stage.mechanism
    try:
        mech = converter.resolve_mechanism(mech)
    except Exception:
        pass
    try:
        gas_template = ct.Solution(mech)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot create Solution for stage '{stage.id}' mechanism '{mech}': {exc}"
        ) from exc

    states = ct.SolutionArray(gas_template, extra=["t"])

    # Fast-path: a plugin-provided CustomStageNetwork (see
    # :mod:`boulder.stage_network`) may already hold the converged profile.
    # Use it verbatim, bypassing the generic CSTR-chain sampler below.
    if network is not None:
        custom_states = getattr(network, "states", None)
        if custom_states is not None and len(custom_states) > 0:
            return custom_states

    t_cumulative = 0.0
    for nid in flow_order:
        reactor = stage_reactors.get(nid)
        if reactor is None or isinstance(reactor, ct.Reservoir):
            continue

        # Estimate residence time
        meta = converter.reactor_meta.get(nid) or {}
        t_res = meta.get("t_res_s")
        if t_res is not None and not math.isnan(float(t_res)):
            dt = float(t_res)
        else:
            dt = _estimate_dt_from_volume(reactor, stage)

        if not math.isnan(dt):
            t_cumulative += dt

        # Map reactor state to the stage mechanism
        try:
            reactor_mech = meta.get("mechanism", mech)
            reactor_thermo = reactor.phase

            if reactor_mech == mech:
                # Same mechanism – direct state copy
                gas_template.state = reactor_thermo.state
            else:
                # Different per-reactor mechanism – map by species name
                gas_template.TP = reactor_thermo.T, reactor_thermo.P
                Y_mapped = np.zeros(gas_template.n_species)
                try:
                    src_gas = ct.Solution(reactor_mech)
                    src_gas.state = reactor_thermo.state
                    for sp in gas_template.species_names:
                        if sp in src_gas.species_names:
                            Y_mapped[gas_template.species_index(sp)] = src_gas.Y[
                                src_gas.species_index(sp)
                            ]
                    Y_sum = Y_mapped.sum()
                    if Y_sum > 0:
                        Y_mapped /= Y_sum
                    gas_template.TPY = reactor_thermo.T, reactor_thermo.P, Y_mapped
                except Exception:
                    # Fallback: use T, P, and whatever species match
                    gas_template.TP = reactor_thermo.T, reactor_thermo.P

            states.append(gas_template.state, t=t_cumulative)  # type: ignore[call-arg]
        except Exception as exc:
            logger.warning(
                "Could not collect state for reactor '%s' in stage '%s': %s",
                nid,
                stage.id,
                exc,
            )

    # If nothing was collected, return an empty SolutionArray
    return states


def _estimate_dt_from_volume(reactor: ct.ReactorBase, stage: Stage) -> float:
    """Estimate residence time [s] from volume, density, and first outgoing MFC."""
    try:
        volume = reactor.volume
        density = reactor.phase.density
        # Try to get mass flow rate from outgoing intra-stage connections
        for conn in stage.intra_connections:
            props = conn.get("properties") or {}
            mdot = props.get("mass_flow_rate")
            if mdot is not None:
                mdot = float(mdot)
                if mdot > 0:
                    return volume * density / mdot
    except Exception:
        pass
    return float("nan")


def _extract_gas_state(
    reactor: ct.ReactorBase,
    mechanism: str,
    converter: "DualCanteraConverter",
) -> ct.Solution:
    """Return a new ``ct.Solution`` carrying the reactor's current thermo state."""
    try:
        mechanism = converter.resolve_mechanism(mechanism)
    except Exception:
        pass
    gas = ct.Solution(mechanism)
    gas.TPY = reactor.phase.T, reactor.phase.P, reactor.phase.Y
    return gas


def _apply_mechanism_switch(
    gas: ct.Solution,
    new_mechanism: str,
    switch_cfg: Dict[str, Any],
    converter: "DualCanteraConverter",
) -> Tuple[ct.Solution, Optional[Dict[str, float]]]:
    """Apply ``mechanism_switch_fn`` plugin to *gas*, returning the mapped gas.

    Parameters
    ----------
    gas :
        Outlet gas in the upstream stage's mechanism.
    new_mechanism :
        Target mechanism for the downstream stage.
    switch_cfg :
        ``{"htol": ..., "Xtol": ...}`` from the connection's ``mechanism_switch``
        block.
    converter :
        Used to access the registered ``mechanism_switch_fn`` plugin.

    Returns
    -------
    (switched_gas, mapping_losses)
        ``mapping_losses`` is ``None`` when the upstream and downstream
        mechanisms are identical (no switch required).

    Raises
    ------
    ValueError
        If a switch is needed but no ``mechanism_switch_fn`` plugin is
        registered.
    """
    # Resolve paths for comparison
    resolved_src = converter.resolve_mechanism(gas.source)
    resolved_tgt = converter.resolve_mechanism(new_mechanism)

    if resolved_src == resolved_tgt:
        return gas, None  # same mechanism, no-op

    switch_fn = getattr(converter.plugins, "mechanism_switch_fn", None)
    if switch_fn is None:
        raise ValueError(
            f"A mechanism_switch is required ('{gas.source}' -> '{new_mechanism}') "
            "but no 'mechanism_switch_fn' plugin is registered. "
            "Register a plugin that provides 'mechanism_switch_fn' via the "
            "Boulder plugin system (entry point 'boulder.plugins' or "
            "BOULDER_PLUGINS env var)."
        )

    htol = float(switch_cfg.get("htol", 1e-4))
    Xtol = float(switch_cfg.get("Xtol", 1e-4))

    switched_gas = switch_fn(gas, resolved_tgt, htol=htol, Xtol=Xtol)

    # Compute approximate mole-fraction loss for the trajectory metadata
    X_loss: Dict[str, float] = {}
    for sp in gas.species_names:
        if sp not in switched_gas.species_names:
            X_loss[sp] = float(gas.X[gas.species_index(sp)])

    return switched_gas, X_loss if X_loss else None
