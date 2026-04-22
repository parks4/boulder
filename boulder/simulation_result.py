"""Typed container for the result of a STONE simulation.

:class:`SimulationResult` replaces the previous loose ``sim_extra`` dict and
per-reactor back-references (e.g. ``reactor._tube_furnace_net``) with a single
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
    (e.g. a Forward-Backward-Sweep PFR) for plugin-specific post-processing.
``trajectory``:
    The :class:`~boulder.lagrangian.LagrangianTrajectory` aggregating all
    stage segments.  Always present (even for a single-stage simulation).
``per_reactor_states``:
    Mapping ``reactor_id -> ct.SolutionArray`` giving the final converged
    thermodynamic state of every non-reservoir reactor.
``scalars``:
    Flat dict of plugin-produced scalars, merged from every
    :attr:`CustomStageNetwork.stage_metadata`.  Keys are namespaced with the
    stage id (``"{stage_id}.{key}"``) to avoid collisions when two stages
    expose the same metric.
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

    def stage_net(self, stage_id: str) -> Optional[ct.ReactorNet]:
        """Convenience accessor mirroring :attr:`stage_nets`.__getitem__."""
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
    3. Flattens each ``CustomStageNetwork.stage_metadata`` into
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
    for stage_id, net in stage_nets.items():
        metadata = getattr(net, "stage_metadata", None)
        if not isinstance(metadata, dict):
            continue
        for key, value in metadata.items():
            scalars[f"{stage_id}.{key}"] = value

    return SimulationResult(
        config=config,
        network=converter.network,
        stage_nets=stage_nets,
        trajectory=trajectory,
        per_reactor_states=per_reactor_states,
        scalars=scalars,
    )
