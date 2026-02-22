"""Lagrangian trajectory representation for staged reactor networks.

A :class:`LagrangianTrajectory` concatenates the per-stage
:class:`~cantera.SolutionArray` segments produced by a staged solve into a
single continuous record with a common cumulative time base.  Species mapping
across stages that use different kinetic mechanisms is handled transparently:
species absent in a given stage appear as ``NaN`` in the merged arrays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cantera as ct
import numpy as np


@dataclass
class TrajectorySegment:
    """One stage's contribution to the full trajectory.

    Attributes
    ----------
    stage_id : str
    mechanism : str
        Resolved path to the kinetic mechanism used in this stage.
    states : ct.SolutionArray
        Per-reactor states in flow order.  Must contain ``T``, ``P``, ``X``,
        ``Y`` arrays.  May carry an extra ``t`` field (residence time within
        the stage, relative, starting from 0 s).
    t_offset : float
        Cumulative time at the *start* of this segment [s].  Set automatically
        by :meth:`LagrangianTrajectory.add_segment`.
    mapping_losses : dict, optional
        Species mole-fraction lost during the mechanism switch that preceded
        this segment (from :func:`~bloc.reactors.switch_mechanism`).
    """

    stage_id: str
    mechanism: str
    states: ct.SolutionArray
    t_offset: float = 0.0
    mapping_losses: Optional[Dict[str, float]] = field(default=None)


class LagrangianTrajectory:
    """Concatenated Lagrangian trajectory across all staged reactor groups.

    Each stage contributes one :class:`TrajectorySegment` (a
    :class:`~cantera.SolutionArray` in flow order through the stage).  The
    class provides convenience properties that concatenate across all segments
    and expose a common time base.

    Attributes
    ----------
    segments : list of TrajectorySegment
        Ordered list of stage contributions.
    viz_network : ct.ReactorNet or None
        Visualization-only :class:`~cantera.ReactorNet` built from all
        converged reactor states after the staged solve completes.
    """

    def __init__(self) -> None:
        self.segments: List[TrajectorySegment] = []
        self.viz_network: Optional[ct.ReactorNet] = None

    # ------------------------------------------------------------------
    # Building the trajectory
    # ------------------------------------------------------------------

    def add_segment(
        self,
        stage_id: str,
        mechanism: str,
        states: ct.SolutionArray,
        mapping_losses: Optional[Dict[str, float]] = None,
    ) -> None:
        """Append a stage's :class:`~cantera.SolutionArray` to the trajectory.

        The cumulative time offset is computed automatically from the previous
        segment's ``t`` axis (if present).

        Parameters
        ----------
        stage_id : str
        mechanism : str
            Kinetic mechanism path for this stage.
        states : ct.SolutionArray
            States in flow order.  Should have an extra ``t`` field [s] that
            gives the residence time within the stage (starting from 0 s).
        mapping_losses : dict, optional
            Species X-losses from the preceding mechanism switch, if any.
        """
        t_offset = 0.0
        if self.segments:
            prev = self.segments[-1]
            t_axis = _get_t_axis(prev.states)
            if t_axis is not None and len(t_axis) > 0:
                last_t = float(t_axis[-1])
                if not math.isnan(last_t):
                    t_offset = prev.t_offset + last_t

        self.segments.append(
            TrajectorySegment(
                stage_id=stage_id,
                mechanism=mechanism,
                states=states,
                t_offset=t_offset,
                mapping_losses=mapping_losses,
            )
        )

    # ------------------------------------------------------------------
    # Concatenated properties
    # ------------------------------------------------------------------

    @property
    def T(self) -> np.ndarray:
        """Temperature [K] along the full trajectory."""
        return np.concatenate([seg.states.T for seg in self.segments])

    @property
    def P(self) -> np.ndarray:
        """Pressure [Pa] along the full trajectory."""
        return np.concatenate([seg.states.P for seg in self.segments])

    @property
    def t(self) -> np.ndarray:
        """Cumulative residence time [s]. ``NaN`` where unknown."""
        parts: List[np.ndarray] = []
        for seg in self.segments:
            t_ax = _get_t_axis(seg.states)
            n = len(seg.states.T)
            if t_ax is not None and len(t_ax) == n:
                parts.append(seg.t_offset + np.asarray(t_ax, dtype=float))
            else:
                parts.append(np.full(n, np.nan))
        return np.concatenate(parts)

    @property
    def species_union(self) -> List[str]:
        """Union of all species names across all stages (insertion-ordered)."""
        seen: Dict[str, bool] = {}
        for seg in self.segments:
            try:
                gas = ct.Solution(seg.mechanism)
                for sp in gas.species_names:
                    seen.setdefault(sp, True)
            except Exception:
                pass
        return list(seen.keys())

    def X(self, species: str) -> np.ndarray:
        """Mole fraction of *species* along the full trajectory. ``NaN`` where absent."""
        parts: List[np.ndarray] = []
        for seg in self.segments:
            try:
                gas = ct.Solution(seg.mechanism)
                if species in gas.species_names:
                    idx = gas.species_index(species)
                    parts.append(seg.states.X[:, idx])
                else:
                    parts.append(np.full(len(seg.states.T), np.nan))
            except Exception:
                parts.append(np.full(len(seg.states.T), np.nan))
        return np.concatenate(parts)

    def Y(self, species: str) -> np.ndarray:
        """Mass fraction of *species* along the full trajectory. ``NaN`` where absent."""
        parts: List[np.ndarray] = []
        for seg in self.segments:
            try:
                gas = ct.Solution(seg.mechanism)
                if species in gas.species_names:
                    idx = gas.species_index(species)
                    parts.append(seg.states.Y[:, idx])
                else:
                    parts.append(np.full(len(seg.states.T), np.nan))
            except Exception:
                parts.append(np.full(len(seg.states.T), np.nan))
        return np.concatenate(parts)

    # ------------------------------------------------------------------
    # Export / visualisation
    # ------------------------------------------------------------------

    def to_dataframe(self) -> Any:
        """Merge into a single ``pandas.DataFrame``.

        Columns: ``stage``, ``t`` [s], ``T`` [K], ``P`` [Pa],
        ``X_<species>`` and ``Y_<species>`` for every species in
        :attr:`species_union`.  Species absent in a given stage are ``NaN``.

        Requires *pandas*.
        """
        import pandas as pd

        all_species = self.species_union
        t_arr = self.t
        T_arr = self.T
        P_arr = self.P

        rows: List[Dict[str, Any]] = []
        offset = 0
        for seg in self.segments:
            n = len(seg.states.T)
            try:
                gas = ct.Solution(seg.mechanism)
                X_matrix = seg.states.X  # shape (n, n_sp)
                Y_matrix = seg.states.Y  # shape (n, n_sp)
            except Exception:
                gas = None
                X_matrix = None
                Y_matrix = None

            for i in range(n):
                row: Dict[str, Any] = {
                    "stage": seg.stage_id,
                    "t": t_arr[offset + i],
                    "T": T_arr[offset + i],
                    "P": P_arr[offset + i],
                }
                for sp in all_species:
                    if gas is not None and sp in gas.species_names:
                        idx = gas.species_index(sp)
                        row[f"X_{sp}"] = (
                            float(X_matrix[i, idx]) if X_matrix is not None else np.nan
                        )
                        row[f"Y_{sp}"] = (
                            float(Y_matrix[i, idx]) if Y_matrix is not None else np.nan
                        )
                    else:
                        row[f"X_{sp}"] = np.nan
                        row[f"Y_{sp}"] = np.nan
                rows.append(row)
            offset += n

        return pd.DataFrame(rows)

    def to_csv(self, path: str) -> None:
        """Export the full trajectory to a CSV file.

        Writes :py:meth:`to_dataframe` output — including ``X_<species>`` and
        ``Y_<species>`` columns — to *path*.

        Parameters
        ----------
        path : str
            Destination file path (created or overwritten).
        """
        self.to_dataframe().to_csv(path, index=False)

    def plot(
        self,
        species: Optional[List[str]] = None,
        t_units: str = "s",
    ) -> Any:
        """Quick plot of temperature (and optionally mole fractions) vs. time.

        Parameters
        ----------
        species : list of str, optional
            Species to plot beneath the temperature panel.
        t_units : str
            ``"s"`` or ``"ms"``.

        Returns
        -------
        matplotlib.figure.Figure
        """
        import matplotlib.pyplot as plt

        t = self.t
        scale = 1e3 if t_units == "ms" else 1.0
        t_label = f"Cumulative residence time [{t_units}]"

        n_panels = 1 + (len(species) if species else 0)
        fig, axes = plt.subplots(n_panels, 1, figsize=(8, 3 * n_panels), sharex=True)
        if n_panels == 1:
            axes = [axes]

        axes[0].plot(t * scale, self.T - 273.15, color="tab:red")
        axes[0].set_ylabel("Temperature [°C]")
        axes[0].grid(True, alpha=0.3)

        for seg in self.segments[1:]:
            for ax in axes:
                ax.axvline(
                    x=seg.t_offset * scale,
                    color="gray",
                    linestyle="--",
                    alpha=0.6,
                    label=f"→ {seg.stage_id}",
                )
        axes[0].legend(fontsize=7, loc="upper right")

        if species:
            for i, sp in enumerate(species):
                axes[i + 1].plot(t * scale, self.X(sp))
                axes[i + 1].set_ylabel(f"X({sp})")
                axes[i + 1].grid(True, alpha=0.3)

        axes[-1].set_xlabel(t_label)
        fig.tight_layout()
        return fig

    def __len__(self) -> int:
        return sum(len(seg.states.T) for seg in self.segments)

    def __repr__(self) -> str:
        stages = [seg.stage_id for seg in self.segments]
        return f"LagrangianTrajectory(stages={stages}, n_points={len(self)})"


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _get_t_axis(states: ct.SolutionArray) -> Optional[np.ndarray]:
    """Return the ``t`` extra field from a SolutionArray, or ``None``."""
    try:
        return np.asarray(states.t, dtype=float)
    except AttributeError:
        return None
