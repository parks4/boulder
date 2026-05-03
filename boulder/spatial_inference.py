"""Infer UI spatial reactor series from staged-solve trajectory data.

When a stage is solved with a plugin :class:`~boulder.stage_network.CustomStageNetwork`
that exposes a multi-point :class:`~cantera.SolutionArray` on ``network.states``,
Boulder records that profile on the Lagrangian trajectory segment for the stage.
This module maps such a segment onto the single logical reactor node id that
owns the stage (exactly one non-:class:`~cantera.Reservoir` reactor in the stage),
so the web UI can render axial plots and optional FBS convergence without each
plugin re-implementing ``spatial_series_fn``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

import cantera as ct  # type: ignore
import numpy as np

from .lagrangian import LagrangianTrajectory, _get_t_axis

if TYPE_CHECKING:
    from .cantera_converter import DualCanteraConverter


def _non_reservoir_reactor_ids(
    stage_node_ids: Sequence[str],
    reactors: Dict[str, ct.ReactorBase],
) -> List[str]:
    out: List[str] = []
    for nid in stage_node_ids:
        r = reactors.get(nid)
        if r is None or isinstance(r, ct.Reservoir):
            continue
        out.append(nid)
    return out


def _resolve_spatial_x_axis(
    states: ct.SolutionArray,
    reactor_meta: Dict[str, Any],
    n_points: int,
) -> np.ndarray:
    """Pick an x-axis for spatial plots: explicit meta, then ``t`` extra, else [0..1]."""
    custom = reactor_meta.get("spatial_x_m")
    if isinstance(custom, (list, tuple)) and len(custom) == n_points:
        return np.asarray(custom, dtype=float)
    if isinstance(custom, np.ndarray) and int(custom.size) == n_points:
        return custom.astype(float)
    t_ax = _get_t_axis(states)
    if t_ax is not None and len(t_ax) == n_points:
        return np.asarray(t_ax, dtype=float)
    if n_points == 1:
        return np.array([0.0], dtype=float)
    return np.linspace(0.0, 1.0, n_points)


def _fbs_from_stage_network(network: Any) -> Optional[List[float]]:
    scalars = getattr(network, "scalars", None)
    if not isinstance(scalars, dict):
        return None
    for key in ("fbs_convergence", "fbs_phi_kw", "fbs_history"):
        raw = scalars.get(key)
        if isinstance(raw, np.ndarray) and raw.size > 0:
            return [float(x) for x in raw.flat]
        if isinstance(raw, (list, tuple)) and len(raw) > 0:
            return [float(x) for x in raw]
    return None


def _solution_array_to_spatial_series(
    states: ct.SolutionArray,
    gas: ct.Solution,
    x_axis: np.ndarray,
    fbs: Optional[List[float]],
) -> Dict[str, Any]:
    """Build ``reactors_series`` entry for ``is_spatial`` plots from a SolutionArray."""
    n_points = len(states)
    species = list(gas.species_names)
    n_spec = len(species)
    t_list: List[float] = []
    p_list: List[float] = []
    x_map: Dict[str, List[float]] = {s: [] for s in species}
    y_map: Dict[str, List[float]] = {s: [] for s in species}

    x_mat = np.asarray(states.X)
    y_mat = np.asarray(states.Y)
    if x_mat.shape != (n_points, n_spec) or y_mat.shape != (n_points, n_spec):
        raise ValueError(
            f"SolutionArray shape mismatch: expected X,Y of shape ({n_points}, {n_spec}), "
            f"got {x_mat.shape}, {y_mat.shape}"
        )

    t_arr = np.asarray(states.T, dtype=float)
    p_arr = np.asarray(states.P, dtype=float)
    for i in range(n_points):
        t_list.append(float(t_arr[i]))
        p_list.append(float(p_arr[i]))
        for j, sp in enumerate(species):
            x_map[sp].append(float(x_mat[i, j]))
            y_map[sp].append(float(y_mat[i, j]))

    series: Dict[str, Any] = {
        "is_spatial": True,
        "x": x_axis.tolist(),
        "T": t_list,
        "P": p_list,
        "X": x_map,
        "Y": y_map,
    }
    if fbs:
        series["fbs_convergence"] = fbs
    return series


def try_infer_spatial_reactor_series(
    converter: "DualCanteraConverter",
    reactor_id: str,
) -> Optional[Dict[str, Any]]:
    """Return a spatial ``reactors_series`` dict if trajectory data uniquely maps to *reactor_id*.

    Preconditions (all must hold):

    * ``converter._staged_trajectory`` exists and ``converter._last_config`` is set.
    * ``reactor_id`` belongs to exactly one stage (via :func:`build_stage_graph`).
    * That stage's trajectory segment has more than one state point.
    * Among reactors in ``converter.reactors`` whose ids lie in that stage, there is
      exactly one that is not a :class:`~cantera.Reservoir` — and it equals *reactor_id*.

    If any check fails, returns ``None`` so explicit ``spatial_series_fn`` remains authoritative.
    """
    traj = getattr(converter, "_staged_trajectory", None)
    cfg = getattr(converter, "_last_config", None)
    if traj is None or cfg is None or not isinstance(traj, LagrangianTrajectory):
        return None

    from .staged_solver import build_stage_graph  # noqa: PLC0415

    plan = build_stage_graph(cfg)
    stage_id = plan.node_to_stage.get(reactor_id)
    if stage_id is None:
        return None

    stage = next((s for s in plan.ordered_stages if s.id == stage_id), None)
    if stage is None:
        return None

    owners = _non_reservoir_reactor_ids(stage.node_ids, converter.reactors)
    if len(owners) != 1 or owners[0] != reactor_id:
        return None

    seg = next((s for s in traj.segments if s.stage_id == stage_id), None)
    if seg is None:
        return None

    states = seg.states
    n_points = len(states)
    if n_points <= 1:
        return None

    meta = converter.reactor_meta.get(reactor_id) or {}
    gas = meta.get("gas_solution") or converter.gas
    if gas is None:
        return None

    x_axis = _resolve_spatial_x_axis(states, meta, n_points)
    net = traj.networks.get(stage_id)
    fbs = _fbs_from_stage_network(net) if net is not None else None

    return _solution_array_to_spatial_series(states, gas, x_axis, fbs)
