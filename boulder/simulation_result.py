"""Typed container for the result of a STONE simulation.

:class:`SimulationResult` replaces the previous loose ``sim_extra`` dict and
per-reactor back-references to plugin internals with a single dataclass that
every downstream consumer — Calculation Note writer, figure generators, KPI
extractors, UI dashboard — can depend on.

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
    A :class:`~boulder.staged_network.StagedReactorNet` — a
    ReactorNet-compatible staged network facade that owns:

    * ``network.visualization_network``: the global, drawable, post-solve
      :class:`cantera.ReactorNet` containing all converged reactors and
      cross-stage connections.
    * ``network.networks``: mapping ``stage_id -> stage solver network``
      (e.g. :class:`~bloc.design_reactors.DesignPFRNet` or
      :class:`~bloc.reactors.DesignTubeFurnaceNet`).
    * ``network.reactors``: unique global reactor objects, deduplicated by
      object identity; same Python instances as those inside each stage
      solver where the solver is reactor-backed.
    * ``network.trajectory``: the :class:`~boulder.lagrangian.LagrangianTrajectory`.
    * ``network.scalars``: flat dict of plugin-produced scalars.

    This facade is **not** a single global CVODE integration — staged solves
    with mechanism switches and custom PFR solvers are not one monolithic ODE
    problem.

``scalars``:
    Read-only convenience property delegating to ``network.scalars``.
``trajectory``:
    Read-only convenience property delegating to ``network.trajectory``.
``per_reactor_states``:
    Mapping ``reactor_id -> ct.SolutionArray`` giving the final converged
    thermodynamic state of every non-reservoir reactor.
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
    from .staged_network import StagedReactorNet


__all__ = ["SimulationResult", "make_simulation_result"]


@dataclass
class SimulationResult:
    """Typed snapshot of a built + solved STONE simulation."""

    config: Dict[str, Any]
    network: "StagedReactorNet"
    per_reactor_states: Dict[str, ct.SolutionArray] = field(default_factory=dict)
    connection_mass_flows_kg_s: Dict[str, float] = field(default_factory=dict)
    connection_endpoints: Dict[str, tuple[str, str]] = field(default_factory=dict)
    node_inlet_mass_flows_kg_s: Dict[str, float] = field(default_factory=dict)
    node_outlet_mass_flows_kg_s: Dict[str, float] = field(default_factory=dict)

    @property
    def scalars(self) -> Dict[str, Any]:
        """Flat plugin-produced scalars, namespaced by ``"{stage_id}.{key}"``.

        Delegates to :attr:`network.scalars`.
        """
        return self.network.scalars

    @property
    def trajectory(self) -> Optional["LagrangianTrajectory"]:
        """Lagrangian trajectory accumulated during the staged solve.

        Delegates to :attr:`network.trajectory`.
        """
        return self.network.trajectory


def make_simulation_result(
    converter: "DualCanteraConverter",
    config: Dict[str, Any],
) -> SimulationResult:
    """Assemble a :class:`SimulationResult` from a solved converter.

    Must be called after
    :meth:`~boulder.cantera_converter.DualCanteraConverter.build_network` has
    returned.  The helper:

    1. Pulls the staged-solve trajectory off the converter.
    2. Constructs a :class:`~boulder.staged_network.StagedReactorNet` facade
       from the visualization network and stage solver networks.
    3. Takes a single-frame :class:`cantera.SolutionArray` snapshot of every
       non-reservoir reactor.
    4. Flattens each ``CustomStageNetwork.scalars`` into the facade's
       ``scalars`` under the ``"{stage_id}.{key}"`` namespace.
    """
    from .staged_network import StagedReactorNet  # noqa: PLC0415

    trajectory = getattr(converter, "_staged_trajectory", None)
    networks: Dict[str, Any] = (
        dict(trajectory.networks) if trajectory is not None else {}
    )

    scalars: Dict[str, Any] = {}
    for stage_id, stage_rnet in networks.items():
        net_scalars = getattr(stage_rnet, "scalars", None)
        if not isinstance(net_scalars, dict):
            continue
        for key, value in net_scalars.items():
            scalars[f"{stage_id}.{key}"] = value

    per_reactor_states: Dict[str, ct.SolutionArray] = {}
    for rid, reactor in getattr(converter, "reactors", {}).items():
        if isinstance(reactor, ct.Reservoir):
            continue
        states = ct.SolutionArray(reactor.phase, extra=["t"])
        states.append(reactor.phase.state, t=0.0)  # type: ignore[call-arg]
        per_reactor_states[rid] = states

    # Authoritative flow map captured once from the solved converter.
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

    viz_net = converter.network
    if viz_net is None:
        raise ValueError(
            "Cannot build SimulationResult: converter.network is None. Call "
            "build_network (and the staged solve) before make_simulation_result."
        )

    staged_net = StagedReactorNet(
        viz_network=viz_net,
        networks=networks,
        trajectory=trajectory,
        scalars=scalars,
    )

    return SimulationResult(
        config=config,
        network=staged_net,
        per_reactor_states=per_reactor_states,
        connection_mass_flows_kg_s=connection_mass_flows_kg_s,
        connection_endpoints=connection_endpoints,
        node_inlet_mass_flows_kg_s=node_inlet_mass_flows_kg_s,
        node_outlet_mass_flows_kg_s=node_outlet_mass_flows_kg_s,
    )
