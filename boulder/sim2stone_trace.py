"""Trace-based fallback for Func1 patterns that cannot be AST-matched.

When ``sim2stone_ast`` cannot identify the exact parametric form of a signal
(e.g. a complex lambda, external table, or multi-step expression), this module
wraps the script execution to record ``(t, value)`` series and compress them
to a ``PiecewiseLinear`` block with an adaptive tolerance.

Usage is intentionally *optional*: import failures (numpy not present) are
silently handled and the caller falls back to an empty signal list.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from .sim2stone_ast import DetectedSignal


def compress_to_piecewise_linear(
    times: List[float],
    values: List[float],
    rtol: float = 1e-3,
    max_points: int = 200,
) -> List[List[float]]:
    """Reduce ``(t, v)`` pairs to a compact piecewise-linear table.

    Uses Douglas–Peucker-style adaptive reduction: keep a point only if it
    deviates by more than ``rtol * max(|values|)`` from the linear interpolant
    between its neighbours.

    Returns a list of ``[t, v]`` pairs.
    """
    if not times or len(times) != len(values):
        return []

    pairs = list(zip(times, values))
    if len(pairs) <= 2:
        return [[t, v] for t, v in pairs]

    scale = max(abs(v) for v in values) or 1.0
    tol = rtol * scale

    def _rdp(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        if len(pts) <= 2:
            return pts
        t0, v0 = pts[0]
        t1, v1 = pts[-1]
        dt = t1 - t0
        max_dev = 0.0
        split = 1
        for i, (ti, vi) in enumerate(pts[1:-1], 1):
            if dt == 0.0:
                dev = abs(vi - v0)
            else:
                alpha = (ti - t0) / dt
                interp = v0 + alpha * (v1 - v0)
                dev = abs(vi - interp)
            if dev > max_dev:
                max_dev = dev
                split = i
        if max_dev > tol:
            left = _rdp(pts[: split + 1])
            right = _rdp(pts[split:])
            return left[:-1] + right
        return [pts[0], pts[-1]]

    reduced = _rdp(pairs)

    # Cap at max_points by uniform sub-sampling if still too dense
    if len(reduced) > max_points:
        step = max(1, len(reduced) // max_points)
        reduced = reduced[::step]
        if reduced[-1] != pairs[-1]:
            reduced.append(pairs[-1])

    return [[float(t), float(v)] for t, v in reduced]


def sample_callable(
    fn: Any,
    t_start: float = 0.0,
    t_end: float = 1.0,
    n_points: int = 500,
) -> Tuple[List[float], List[float]]:
    """Sample a callable ``fn(t)`` uniformly over ``[t_start, t_end]``.

    Returns ``(times, values)``.  Silently skips points where the callable
    raises.
    """
    times: List[float] = []
    values: List[float] = []
    if n_points < 2:
        n_points = 2
    dt = (t_end - t_start) / (n_points - 1)
    for i in range(n_points):
        t = t_start + i * dt
        try:
            v = float(fn(t))
            times.append(t)
            values.append(v)
        except Exception:
            pass
    return times, values


def trace_func1_to_signal(
    func1_obj: Any,
    signal_id: str,
    t_start: float = 0.0,
    t_end: Optional[float] = None,
    n_points: int = 500,
    rtol: float = 1e-3,
) -> Optional[DetectedSignal]:
    """Sample a ``ct.Func1`` or callable and emit a ``PiecewiseLinear`` signal.

    Parameters
    ----------
    func1_obj:
        Any callable that accepts a float ``t`` and returns a float.
    signal_id:
        STONE id to assign to the emitted signal block.
    t_start, t_end:
        Time range to sample.  If ``t_end`` is ``None``, defaults to 1e-7 for
        objects with ``Gaussian`` in their type, else 1.0.
    n_points:
        Number of sample points before compression.
    rtol:
        Relative tolerance for Douglas–Peucker compression.

    Returns
    -------
    DetectedSignal or None
    """
    if t_end is None:
        try:
            ftype = str(func1_obj.type)
            t_end = 1e-7 if "Gaussian" in ftype else 1.0
        except Exception:
            t_end = 1.0

    times, values = sample_callable(
        func1_obj, t_start=t_start, t_end=t_end, n_points=n_points
    )
    if not times:
        return None

    points = compress_to_piecewise_linear(times, values, rtol=rtol)
    if not points:
        return None

    return DetectedSignal(
        signal_id=signal_id,
        kind="PiecewiseLinear",
        params={"points": points},
        source_var=signal_id,
        derived_via="trace_reconstruction",
    )
