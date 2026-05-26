"""Staged solving of Boulder reactor networks.

When a STONE YAML declares a top-level ``groups`` section, each group
represents an independent sub-network (stage) that is solved sequentially.
Stages are connected by *inter-stage connections* whose ``mechanism_switch``
block triggers species mapping when the two groups use different kinetic
mechanisms.

Public API
----------
- :func:`build_stage_graph`         – parse config, return a :class:`StageExecutionPlan`
- :func:`synthesize_interface_nodes` – return node/connection dicts for all iface reservoirs
- :func:`solve_staged`              – execute the plan, return a
  :class:`~boulder.lagrangian.LagrangianTrajectory`

Architecture (with interface_reservoirs enabled)
------------------------------------------------
1. ``build_stage_graph`` partitions nodes/connections by group, topologically
   sorts the stages, and validates acyclicity.  Each :class:`InterStageConnection`
   is assigned a ``reservoir_id`` (``"{id}__iface"``) that will become a
   ``ct.Reservoir`` at the stage boundary.
2. ``solve_staged`` iterates in order:
   a. Build a sub-ReactorNet for the stage including:
      - upstream-side outlet MFCs to the interface reservoirs declared in
        ``stage.inter_connections_out``.
      - downstream-side inlet MFCs from the interface reservoirs declared in
        ``stage.inter_connections_in``.
   b. Solve the sub-network.
   c. Extract outlet state(s) and write them into the interface reservoirs
      (applying ``mechanism_switch`` when declared).
   d. Record states in the trajectory.
3. After all stages: build a single visualization ReactorNet from all converged
   reactor states with all connections (including inter-stage) restored.

Legacy mode (``interface_reservoirs=False``)
--------------------------------------------
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

    When ``interface_reservoirs=True`` (default in new runs), each instance
    corresponds to exactly one ``ct.Reservoir`` named ``reservoir_id``.  The
    upstream stage builds an outlet MFC *into* the reservoir; the downstream
    stage builds an inlet MFC *from* it.  The reservoir holds the converged
    interface state (T, P, Y) after the upstream solve, with ``mechanism_switch``
    applied when present.

    Legacy mode (``interface_reservoirs=False``): the connection remains virtual
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
    def reservoir_id(self) -> str:
        """Deterministic id for the synthesised interface :class:`~cantera.Reservoir`."""
        return f"{self.id}__iface"

    @property
    def outlet_mfc_id(self) -> str:
        """Id for the upstream-side MFC connecting source to interface reservoir."""
        return f"{self.id}__iface_out"

    @property
    def inlet_mfc_id(self) -> str:
        """Id for the downstream-side MFC connecting interface reservoir to target."""
        return f"{self.id}__iface_in"


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
# synthesize_interface_nodes
# ---------------------------------------------------------------------------


def synthesize_interface_nodes(
    plan: StageExecutionPlan,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return synthetic node and connection dicts for all interface reservoirs.

    One :class:`~cantera.Reservoir` is created per :class:`InterStageConnection`
    in *plan*.  Each reservoir is flanked by two ``MassFlowController`` stubs:
    an outlet MFC from the source to the reservoir (in the upstream stage) and
    an inlet MFC from the reservoir to the target (in the downstream stage).

    The returned dicts follow the same normalized schema as regular nodes and
    connections so they can be injected directly into ``build_sub_network``.

    Parameters
    ----------
    plan :
        Execution plan produced by :func:`build_stage_graph`.

    Returns
    -------
    (nodes, connections)
        ``nodes`` – one ``Reservoir`` dict per inter-stage connection.
        ``connections`` – two ``MassFlowController`` dicts per inter-stage
        connection (outlet side + inlet side).  ``mass_flow_rate`` is copied
        from ``ic.properties`` when explicitly declared.
    """
    nodes: List[Dict[str, Any]] = []
    connections: List[Dict[str, Any]] = []

    for ic in plan.all_inter_connections:
        # Interface Reservoir node
        nodes.append(
            {
                "id": ic.reservoir_id,
                "type": "Reservoir",
                "properties": {
                    # Placeholder T/P/composition - overwritten after upstream solve
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    # Metadata fields forwarded to the frontend
                    "stage_interface": True,
                    "upstream_stage": ic.source_stage,
                    "downstream_stage": ic.target_stage,
                    "source_node": ic.source_node,
                    "target_node": ic.target_node,
                },
                "metadata": {
                    "stage_interface": True,
                    "upstream_stage": ic.source_stage,
                    "downstream_stage": ic.target_stage,
                    "source_node": ic.source_node,
                    "target_node": ic.target_node,
                    "original_connection_id": ic.id,
                },
            }
        )

        mdot = ic.properties.get("mass_flow_rate")
        out_props: Dict[str, Any] = {}
        in_props: Dict[str, Any] = {}
        if mdot is not None:
            out_props["mass_flow_rate"] = mdot
            in_props["mass_flow_rate"] = mdot

        # Upstream-side MFC: source_node → iface reservoir  (in upstream stage)
        connections.append(
            {
                "id": ic.outlet_mfc_id,
                "type": "MassFlowController",
                "source": ic.source_node,
                "target": ic.reservoir_id,
                "properties": out_props,
                "metadata": {"stage_interface": True, "side": "outlet"},
                "group": ic.source_stage,
            }
        )

        # Downstream-side MFC: iface reservoir → target_node  (in downstream stage)
        connections.append(
            {
                "id": ic.inlet_mfc_id,
                "type": "MassFlowController",
                "source": ic.reservoir_id,
                "target": ic.target_node,
                "properties": in_props,
                "metadata": {"stage_interface": True, "side": "inlet"},
                "group": ic.target_stage,
            }
        )

    return nodes, connections


# ---------------------------------------------------------------------------
# solve_staged
# ---------------------------------------------------------------------------


def solve_staged(
    converter: "DualCanteraConverter",
    plan: StageExecutionPlan,
    config: Dict[str, Any],
    progress_callback: Optional[Callable] = None,
    interface_reservoirs: bool = False,
) -> "LagrangianTrajectory":
    """Execute a :class:`StageExecutionPlan` sequentially.

    For each stage:

    1. Filter nodes/connections for this stage.
    2. If *interface_reservoirs* is ``True``: inject iface reservoirs and build
       real MFCs on both sides of each stage boundary (see
       :func:`synthesize_interface_nodes`).
       Otherwise (legacy): initialise inter-stage-inlet reactors from upstream
       outlet state via ``inlet_states``.
    3. Build stage sub-ReactorNet.
    4. Solve according to ``stage.solve_directive``.
    5. Extract outlet state(s), apply ``mechanism_switch`` if present, and
       write the result into the interface reservoir (or ``inlet_states``).
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
    interface_reservoirs :
        When ``True``, synthesise a ``ct.Reservoir`` + two ``MassFlowController``
        objects for every inter-stage connection so that each stage solve sees
        the full mass flow (not just intra-stage flow).  Default ``False``
        (legacy behaviour) while the feature is validated.

    Returns
    -------
    LagrangianTrajectory
    """
    from .lagrangian import LagrangianTrajectory

    trajectory = LagrangianTrajectory()

    # ``inlet_states[node_id]`` holds the ct.Solution ready to initialise the
    # downstream reactor.  In legacy mode this is the primary handoff mechanism.
    # In interface_reservoirs mode it is kept as an inspection snapshot only.
    inlet_states: Dict[str, ct.Solution] = {}

    # Pre-build all interface reservoirs and associated connection dicts once so
    # both upstream and downstream stage builds can reference them.
    iface_node_dicts: Dict[str, Dict[str, Any]] = {}  # reservoir_id -> node dict
    iface_conns_by_stage: Dict[str, List[Dict[str, Any]]] = {}  # stage_id -> conn dicts
    if interface_reservoirs:
        iface_nodes, iface_conns = synthesize_interface_nodes(plan)
        for nd in iface_nodes:
            iface_node_dicts[nd["id"]] = nd
        for cd in iface_conns:
            grp = cd.get("group", "")
            iface_conns_by_stage.setdefault(grp, []).append(cd)

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

        # Augment with iface reservoir nodes relevant to this stage
        extra_nodes: List[Dict[str, Any]] = []
        extra_conns: List[Dict[str, Any]] = []
        if interface_reservoirs:
            # Include reservoirs for outgoing connections (outlet side)
            for ic in stage.inter_connections_out:
                nd = iface_node_dicts.get(ic.reservoir_id)
                if nd is not None:
                    extra_nodes.append(nd)
            # Include reservoirs for incoming connections (inlet side)
            for ic in stage.inter_connections_in:
                nd = iface_node_dicts.get(ic.reservoir_id)
                if nd is not None:
                    extra_nodes.append(nd)
            extra_conns = iface_conns_by_stage.get(stage.id, [])

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

            if interface_reservoirs:
                # Replace the placeholder iface reservoir with a new one holding the
                # converged outlet state.  Cantera Reservoir objects are immutable
                # after construction; the only reliable way to update their state
                # is to build a fresh Reservoir from the converged gas and swap it
                # into self.reactors before the downstream stage builds its inlet MFC.
                new_res_gas = converter._get_gas_for_mech(stage.mechanism)
                new_res_gas.TPY = outlet_gas.T, outlet_gas.P, outlet_gas.Y
                new_iface_res = ct.Reservoir(new_res_gas, clone=False)
                new_iface_res.name = ic.reservoir_id
                converter.reactors[ic.reservoir_id] = new_iface_res
                converter.reactor_meta.setdefault(ic.reservoir_id, {}).update(
                    {
                        "mechanism": stage.mechanism,
                        "gas_solution": new_res_gas,
                        "stage_interface": True,
                        "upstream_stage": ic.source_stage,
                        "downstream_stage": ic.target_stage,
                        "source_node": ic.source_node,
                        "target_node": ic.target_node,
                    }
                )
                logger.debug(
                    "Interface reservoir '%s' updated: T=%.1f K", ic.reservoir_id, outlet_gas.T
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

    # Build visualization ReactorNet from all converged states
    logger.info("Staged solve complete – building visualization ReactorNet.")
    viz_net = converter.build_viz_network(
        all_connections=config.get("connections") or [],
        built_conn_ids=set(converter.connections.keys()) | set(converter.walls.keys()),
    )
    trajectory.viz_network = viz_net

    return trajectory


# ---------------------------------------------------------------------------
# Helpers used by solve_staged
# ---------------------------------------------------------------------------


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
