"""Staged solving of Boulder reactor networks.

When a STONE YAML declares a top-level ``groups`` section, each group
represents an independent sub-network (stage) that is solved sequentially.
Stages are connected by *inter-stage connections* whose ``mechanism_switch``
block triggers species mapping when the two groups use different kinetic
mechanisms.

Public API
----------
- :func:`build_stage_graph` – parse config, return a :class:`StageExecutionPlan`
- :func:`solve_staged`       – execute the plan, return a
  :class:`~boulder.lagrangian.LagrangianTrajectory`

Architecture
------------
1. ``build_stage_graph`` partitions nodes/connections by group, topologically
   sorts the stages, and validates acyclicity.
2. ``solve_staged`` iterates in order:
   a. Build a sub-ReactorNet for the stage (only intra-stage connections).
   b. Initialise inter-stage-inlet reactors from the upstream outlet state
      (no Reservoir injected – just ``reactor.phase.TPY``).
   c. Solve the sub-network.
   d. Extract outlet state(s).
   e. If the outgoing connection carries ``mechanism_switch``, call the
      registered ``mechanism_switch_fn`` plugin.
   f. Record states in the trajectory.
3. After all stages: build a single visualization ReactorNet from all converged
   reactor states with all connections (including inter-stage) restored.
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

    At solve time, the connection is *virtual* – it is not built as a Cantera
    :class:`~cantera.MassFlowController`.  Instead, the upstream reactor's
    outlet state is used to initialise the downstream reactor directly.

    The connection is *restored* in the final visualization ReactorNet so the
    full topology is visible in ``ReactorNet.draw()`` and Sankey diagrams.
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


@dataclass
class Stage:
    """A single group in the staged execution plan."""

    id: str
    mechanism: str
    #: ``"advance_to_steady_state"`` or ``"advance"``.
    solve_directive: str = "advance_to_steady_state"
    #: Used only when *solve_directive* is ``"advance"``.
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

    # Build Stage objects from groups config
    stages: Dict[str, Stage] = {}
    for gid, gcfg in groups_cfg.items():
        gcfg = gcfg or {}
        stages[gid] = Stage(
            id=gid,
            mechanism=str(gcfg.get("mechanism", default_mechanism)),
            solve_directive=str(gcfg.get("solve", "advance_to_steady_state")),
            advance_time=float(gcfg.get("advance_time", 1.0)),
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
# solve_staged
# ---------------------------------------------------------------------------


def solve_staged(
    converter: "DualCanteraConverter",
    plan: StageExecutionPlan,
    config: Dict[str, Any],
    progress_callback: Optional[Callable] = None,
) -> "LagrangianTrajectory":
    """Execute a :class:`StageExecutionPlan` sequentially.

    For each stage:

    1. Filter nodes/connections for this stage.
    2. Initialise inter-stage-inlet reactors from upstream outlet state.
    3. Build stage sub-ReactorNet (intra-stage connections only).
    4. Solve according to ``stage.solve_directive``.
    5. Extract outlet state(s) and apply ``mechanism_switch`` if present.
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

    Returns
    -------
    LagrangianTrajectory
    """
    from .lagrangian import LagrangianTrajectory

    trajectory = LagrangianTrajectory()

    # ``inlet_states[node_id]`` holds the ct.Solution ready to initialise
    # the downstream reactor (already mechanism-switched if needed).
    inlet_states: Dict[str, ct.Solution] = {}

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

        # Build sub-network and solve
        network, stage_reactors = converter.build_sub_network(
            stage_nodes=stage_nodes,
            stage_connections=stage.intra_connections,
            stage_mechanism=stage.mechanism,
            inlet_states=inlet_states,
            stage_id=stage.id,
            stage=stage,
        )

        # Collect SolutionArray in flow order through the stage
        flow_order = _flow_order_within_stage(stage)
        states = _collect_stage_states(stage, stage_reactors, flow_order, converter)
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

            inlet_states[ic.target_node] = outlet_gas

        trajectory.add_segment(
            stage_id=stage.id,
            mechanism=stage.mechanism,
            states=states,
            mapping_losses=mapping_losses,
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
    stage_reactors: Dict[str, ct.Reactor],
    flow_order: List[str],
    converter: "DualCanteraConverter",
) -> ct.SolutionArray:
    """Collect per-reactor final states into a SolutionArray in flow order.

    Residence time is taken from ``converter.reactor_meta[rid]["t_res_s"]``
    when available (set by Bloc's post-build hook for DesignTorch / DesignPSR).
    For CSTR chains the cells have volumes; residence time is approximated as
    ``volume * density / mass_flow_rate`` using the first available outgoing
    mass flow rate; if unknown, the field is ``NaN``.
    """
    # Resolve mechanism and create template
    mech = stage.mechanism
    if converter.plugins.mechanism_path_resolver:
        try:
            mech = converter.plugins.mechanism_path_resolver(mech)
        except Exception:
            pass
    try:
        gas_template = ct.Solution(mech)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot create Solution for stage '{stage.id}' mechanism '{mech}': {exc}"
        ) from exc

    states = ct.SolutionArray(gas_template, extra=["t"])

    # If a reactor carries a full spatial profile from a custom solver
    # (e.g. DesignPFRNet.advance()), return it directly without re-sampling.
    for nid in flow_order:
        r = stage_reactors.get(nid)
        if r is not None and hasattr(r, "_boulder_states"):
            return r._boulder_states  # full FBS SolutionArray — use directly

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


def _estimate_dt_from_volume(reactor: ct.Reactor, stage: Stage) -> float:
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
    reactor: ct.Reactor,
    mechanism: str,
    converter: "DualCanteraConverter",
) -> ct.Solution:
    """Return a new ``ct.Solution`` carrying the reactor's current thermo state."""
    if converter.plugins.mechanism_path_resolver:
        try:
            mechanism = converter.plugins.mechanism_path_resolver(mechanism)
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
    resolve = converter.plugins.mechanism_path_resolver
    resolved_src = resolve(gas.source) if resolve else gas.source
    resolved_tgt = resolve(new_mechanism) if resolve else new_mechanism

    if resolved_src == resolved_tgt:
        return gas, None  # same mechanism, no-op

    switch_fn = getattr(converter.plugins, "mechanism_switch_fn", None)
    if switch_fn is None:
        raise ValueError(
            f"A mechanism_switch is required ('{gas.source}' → '{new_mechanism}') "
            "but no 'mechanism_switch_fn' plugin is registered. "
            "Install the 'bloc' package and ensure its plugins are loaded."
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
