"""Protocol describing custom stage-level ReactorNet implementations.

Boulder's default stage solver treats each stage as a :class:`cantera.ReactorNet`
and calls ``advance_to_steady_state`` or ``advance``.  Plugins that need a
custom stage solver can provide a
subclass of :class:`cantera.ReactorNet` that implements the
:class:`CustomStageNetwork` protocol declared here.

A plugin opts in by registering the class via :func:`register_reactor_builder`
(``network_class=...``) or exposing it on one of its reactors as the
``NETWORK_CLASS`` attribute, and by implementing the two read-only properties
below.  Boulder then:

1. Stores the concrete network on the :class:`LagrangianTrajectory`
   (``trajectory.networks[stage_id]``) so downstream callers (Calculation
   Note, figures, KPIs) can inspect any plugin-specific scalars via
   :attr:`CustomStageNetwork.scalars`.
2. Uses :attr:`CustomStageNetwork.states` verbatim when collecting the
   per-stage Lagrangian segment — no CSTR chain re-sampling.

The protocol is intentionally minimal: it adds no requirements beyond what
:class:`cantera.ReactorNet` already provides, so plain ``ct.ReactorNet``
instances silently remain valid stage networks (they simply fail the
``isinstance(..., CustomStageNetwork)`` check and fall back to the generic
CSTR-chain sampler).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable

import cantera as ct

__all__ = ["CustomStageNetwork"]


@runtime_checkable
class CustomStageNetwork(Protocol):
    """Opt-in contract for plugin-provided stage networks.

    Implementations SHOULD subclass :class:`cantera.ReactorNet` so that the
    generic staged solver can still drive them via ``advance_to_steady_state``
    or ``advance``.  The two properties below are what Boulder relies on to
    surface solver-specific output.

    Notes
    -----
    * ``states`` may return ``None`` before :meth:`advance` has been
      called.  Callers MUST handle ``None`` by falling back to generic
      per-reactor state sampling.
    * ``scalars`` SHOULD contain JSON-serialisable scalars only so it
      can be written into Excel Calculation Notes without further coercion.
    """

    @property
    def states(self) -> Optional[ct.SolutionArray]:
        """Full SolutionArray describing the converged stage profile, or ``None``."""
        ...

    @property
    def scalars(self) -> Dict[str, Any]:
        """Plugin-specific scalars produced by the solver (heat loss, t_res, ...)."""
        ...
