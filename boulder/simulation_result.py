"""Typed container for the result of a STONE simulation.

:class:`SimulationResult` replaces the previous loose ``sim_extra`` dict and
per-reactor back-references to plugin internals with a single
dataclass that every downstream consumer — Calculation Note writer, figure
generators, KPI extractors, UI dashboard — can depend on.

Construction
------------
Call :func:`make_simulation_result` after
:meth:`boulder.cantera_converter.DualCanteraConverter.build_network` returns.
The helper inspects the converter, the staged-solve trajectory and each
:class:`~boulder.stage_network.CustomStageNetwork` to populate the fields.

Structure
---------
``config``:
    The fully normalised (post :func:`boulder.config.normalize_config`) config.
``network``:
    Visualization :class:`cantera.ReactorNet` produced by
    :meth:`~boulder.cantera_converter.DualCanteraConverter.build_viz_network`.
``stage_nets``:
    Mapping ``stage_id -> ReactorNet`` exposing the concrete stage solvers
    (i.e. plugin-specific stage networks) for plugin-specific post-processing.
``trajectory``:
    The :class:`~boulder.lagrangian.LagrangianTrajectory` aggregating all
    stage segments.  Always present (even for a single-stage simulation).
``per_reactor_states``:
    Mapping ``reactor_id -> ct.SolutionArray`` giving the final converged
    thermodynamic state of every non-reservoir reactor.
``scalars``:
    Flat dict of plugin-produced scalars, merged from every
    :attr:`CustomStageNetwork.scalars`.  Keys are namespaced with the
    stage id (``"{stage_id}.{key}"``) to avoid collisions when two stages
    expose the same metric.
``connection_mass_flows_kg_s``:
    Mapping ``connection_id -> mass flow rate`` captured from the solved network.
``connection_endpoints``:
    Mapping ``connection_id -> (source_node_id, target_node_id)`` from config.
``node_inlet_mass_flows_kg_s`` / ``node_outlet_mass_flows_kg_s``:
    Per-node aggregate inlet/outlet mass flows derived from connection maps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

import cantera as ct

if TYPE_CHECKING:
    from .cantera_converter import DualCanteraConverter
    from .lagrangian import LagrangianTrajectory


__all__ = ["SimulationResult", "make_simulation_result"]


@dataclass
class SimulationResult:
    """Typed snapshot of a built + solved STONE simulation."""

    config: Dict[str, Any]
    network: ct.ReactorNet
    stage_nets: Dict[str, ct.ReactorNet] = field(default_factory=dict)
    trajectory: Optional["LagrangianTrajectory"] = None
    per_reactor_states: Dict[str, ct.SolutionArray] = field(default_factory=dict)
    scalars: Dict[str, Any] = field(default_factory=dict)
    connection_mass_flows_kg_s: Dict[str, float] = field(default_factory=dict)
    connection_endpoints: Dict[str, tuple[str, str]] = field(default_factory=dict)
    node_inlet_mass_flows_kg_s: Dict[str, float] = field(default_factory=dict)
    node_outlet_mass_flows_kg_s: Dict[str, float] = field(default_factory=dict)

    def stage_net(self, stage_id: str) -> Optional[ct.ReactorNet]:
        """Return the reactor net for ``stage_id``, like :attr:`stage_nets` lookup."""
        return self.stage_nets.get(stage_id)


def make_simulation_result(
    converter: "DualCanteraConverter",
    config: Dict[str, Any],
) -> SimulationResult:
    """Assemble a :class:`SimulationResult` from a solved converter.

    Must be called after
    :meth:`~boulder.cantera_converter.DualCanteraConverter.build_network` has
    returned.  The helper:

    1. Pulls the staged-solve trajectory off the converter.
    2. Takes a single-frame :class:`cantera.SolutionArray` snapshot of every
       non-reservoir reactor.
    3. Flattens each ``CustomStageNetwork.scalars`` into
       :attr:`SimulationResult.scalars` under the ``"{stage_id}.{key}"``
       namespace.
    """
    trajectory = getattr(converter, "_staged_trajectory", None)
    stage_nets: Dict[str, ct.ReactorNet] = (
        dict(trajectory.stage_nets) if trajectory is not None else {}
    )

    per_reactor_states: Dict[str, ct.SolutionArray] = {}
    for rid, reactor in getattr(converter, "reactors", {}).items():
        if isinstance(reactor, ct.Reservoir):
            continue
        states = ct.SolutionArray(reactor.phase, extra=["t"])
        states.append(reactor.phase.state, t=0.0)  # type: ignore[call-arg]
        per_reactor_states[rid] = states

    scalars: Dict[str, Any] = {}
    for stage_id, stage_rnet in stage_nets.items():
        net_scalars = getattr(stage_rnet, "scalars", None)
        if not isinstance(net_scalars, dict):
            continue
        for key, value in net_scalars.items():
            scalars[f"{stage_id}.{key}"] = value

    # Authoritative flow map captured once from the solved converter.
    # This avoids re-probing transient flow-device state later in reporting.
    connection_endpoints: Dict[str, tuple[str, str]] = {}
    for conn in config.get("connections") or []:
        cid = conn.get("id")
        src = conn.get("source")
        tgt = conn.get("target")
        if cid and src and tgt:
            connection_endpoints[str(cid)] = (str(src), str(tgt))

    connection_mass_flows_kg_s: Dict[str, float] = {}
    node_inlet_mass_flows_kg_s: Dict[str, float] = {}
    node_outlet_mass_flows_kg_s: Dict[str, float] = {}
    for cid, dev in getattr(converter, "connections", {}).items():
        # Only flow devices expose mass_flow_rate; walls and custom non-flow
        # objects are ignored.
        try:
            mdot = float(dev.mass_flow_rate)
        except Exception:
            continue
        connection_mass_flows_kg_s[cid] = mdot
        endpoints = connection_endpoints.get(cid)
        if endpoints is None:
            continue
        src, tgt = endpoints
        node_outlet_mass_flows_kg_s[src] = (
            node_outlet_mass_flows_kg_s.get(src, 0.0) + mdot
        )
        node_inlet_mass_flows_kg_s[tgt] = (
            node_inlet_mass_flows_kg_s.get(tgt, 0.0) + mdot
        )

    net = converter.network
    if net is None:
        raise ValueError(
            "Cannot build SimulationResult: converter.network is None. Call "
            "build_network (and the staged solve) before make_simulation_result."
        )
    return SimulationResult(
        config=config,
        network=net,
        stage_nets=stage_nets,
        trajectory=trajectory,
        per_reactor_states=per_reactor_states,
        scalars=scalars,
        connection_mass_flows_kg_s=connection_mass_flows_kg_s,
        connection_endpoints=connection_endpoints,
        node_inlet_mass_flows_kg_s=node_inlet_mass_flows_kg_s,
        node_outlet_mass_flows_kg_s=node_outlet_mass_flows_kg_s,
    )
