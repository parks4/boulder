"""ReactorNet-compatible staged network facade.

A :class:`StagedReactorNet` wraps the two internal views produced by Boulder's
staged solver — the global visualization :class:`~cantera.ReactorNet` and the
mapping of ``stage_id`` to concrete stage solver networks — behind a single
public object.

This is a **duck-typed facade, not a Cantera C++ integrator**.  The staged
solve may involve mechanism switches, custom PFR solvers, and multiple CVODE
integrations; it is not one monolithic ODE problem.  Do not call
``advance()`` or ``advance_to_steady_state()`` on this object — those methods
are intentionally absent.  If you truly need raw CVODE stepping, use
``network.visualization_network.advance(...)``.

Reactor-identity invariant
--------------------------
``StagedReactorNet.reactors`` returns the unique set of global reactor
objects from the visualization network (deduplicated by object identity).
``StagedReactorNet.networks[stage_id].reactors`` returns the stage-local
subset.  When a stage solver is reactor-backed those stage-local reactors are
the **same Python objects** as the corresponding entries in
``StagedReactorNet.reactors``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import cantera as ct

if TYPE_CHECKING:
    from .lagrangian import LagrangianTrajectory


__all__ = ["StagedReactorNet"]


class StagedReactorNet:
    """ReactorNet-compatible staged network facade.

    Parameters
    ----------
    viz_network:
        The global, drawable, post-solve :class:`~cantera.ReactorNet` built
        from all converged reactors and cross-stage connections.
    networks:
        Mapping ``stage_id -> stage solver network`` (may be plugin-defined
        custom ``ReactorNet``-like types).
    trajectory:
        The :class:`~boulder.lagrangian.LagrangianTrajectory` accumulated
        during the staged solve.
    scalars:
        Flat dict of plugin-produced scalars, namespaced by
        ``"{stage_id}.{key}"``.
    """

    def __init__(
        self,
        viz_network: ct.ReactorNet,
        networks: Optional[Dict[str, Any]] = None,
        trajectory: Optional["LagrangianTrajectory"] = None,
        scalars: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._viz_network = viz_network
        self.networks: Dict[str, Any] = networks or {}
        self.trajectory = trajectory
        self.scalars: Dict[str, Any] = scalars or {}

    # ------------------------------------------------------------------
    # visualization_network: low-level access to the raw ct.ReactorNet
    # ------------------------------------------------------------------

    @property
    def visualization_network(self) -> ct.ReactorNet:
        """Raw drawable :class:`~cantera.ReactorNet` for Cantera-internal callers.

        Use this when a function strictly requires a ``ct.ReactorNet`` (e.g.
        Sankey generation, ``draw()`` customisation, or ``_extract_node_data``
        in ``calc_note``).  For most uses, prefer the facade methods directly.
        """
        return self._viz_network

    # ------------------------------------------------------------------
    # ReactorNet-compatible surface
    # ------------------------------------------------------------------

    @property
    def reactors(self) -> List[ct.ReactorBase]:
        """Unique global reactors from the visualization network.

        Deduplicated by object identity to handle shared-Solution Cantera
        quirks where the same reactor can appear multiple times in a
        ReactorNet built from converged state snapshots.
        """
        seen: set = set()
        result: List[ct.ReactorBase] = []
        for r in self._viz_network.reactors:
            if id(r) not in seen:
                seen.add(id(r))
                result.append(r)
        return result

    def draw(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate :py:meth:`~cantera.ReactorNet.draw` to the visualization network."""
        return self._viz_network.draw(*args, **kwargs)

    @property
    def time(self) -> float:
        """Current time of the visualization network [s]."""
        return float(self._viz_network.time)

    # ------------------------------------------------------------------
    # Stage access
    # ------------------------------------------------------------------

    def get_stage(self, stage_id: str) -> Optional[Any]:
        """Return the concrete stage solver network for *stage_id*, or ``None``."""
        return self.networks.get(stage_id)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        stage_ids = list(self.networks.keys())
        n_reactors = len(self.reactors)
        return (
            f"StagedReactorNet("
            f"stages={stage_ids}, "
            f"n_reactors={n_reactors})"
        )
