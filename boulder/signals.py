"""Signal registry for Boulder's causal layer (Phase A).

Each *source block* in the STONE ``signals:`` section maps to a factory
function here that returns either a ``cantera.Func1`` object or a plain
Python callable with signature ``f(t: float) -> float``.

Source blocks are stateless primitives (Constant, Sine, Gaussian, Step,
Ramp, PiecewiseLinear, FromCSV) and combinators that reference prior signal
IDs (Sum, Gain, Integrator).

Usage::

    from boulder.signals import build_signal_registry

    signals_block = [
        {"id": "pulse", "Gaussian": {"peak": 1.9e-19, "center": 24e-9, "fwhm": 7.06e-9}},
        {"id": "tau", "Constant": {"value": 0.1}},
        {"id": "double", "Sum": {"inputs": ["pulse", "pulse"]}},
    ]
    registry = build_signal_registry(signals_block)
    # registry["pulse"] is a ct.Func1
    # registry["tau"](3.0) == 0.1

"""

from __future__ import annotations

import csv
import math
from typing import Any, Callable, Dict, List, Optional, Union

import cantera as ct

SignalObj = Union[ct.Func1, Callable[[float], float]]


# ---------------------------------------------------------------------------
# Primitive source factories
# ---------------------------------------------------------------------------


def _make_constant(spec: Dict[str, Any]) -> Callable[[float], float]:
    """Constant source: returns ``value`` regardless of time.

    Args
    ----
    spec : dict with key ``value`` (float).
    """
    value = float(spec["value"])
    return lambda _t: value


def _make_sine(spec: Dict[str, Any]) -> Callable[[float], float]:
    """Sine wave: ``A * sin(2π·f·t + φ) + offset``.

    Args
    ----
    spec : dict with keys ``amplitude``, ``frequency`` (Hz), ``phase`` (rad,
        default 0), ``offset`` (default 0).
    """
    A = float(spec["amplitude"])
    f = float(spec["frequency"])
    phi = float(spec.get("phase", 0.0))
    offset = float(spec.get("offset", 0.0))
    return lambda t: A * math.sin(2.0 * math.pi * f * t + phi) + offset


def _make_gaussian(spec: Dict[str, Any]) -> ct.Func1:
    """Gaussian pulse — wraps ``ct.Func1('Gaussian', [peak, center, fwhm])``.

    Args
    ----
    spec : dict with keys ``peak``, ``center`` (s), ``fwhm`` (s).
    """
    peak = float(spec["peak"])
    center = float(spec["center"])
    fwhm = float(spec["fwhm"])
    return ct.Func1("Gaussian", [peak, center, fwhm])


def _make_step(spec: Dict[str, Any]) -> Callable[[float], float]:
    """Heaviside step at ``t_step``.

    Args
    ----
    spec : dict with keys ``t_step``, ``value_before``, ``value_after``.
    """
    t_step = float(spec["t_step"])
    before = float(spec["value_before"])
    after = float(spec["value_after"])
    return lambda t: after if t >= t_step else before


def _make_ramp(spec: Dict[str, Any]) -> Callable[[float], float]:
    """Linear ramp between ``t_start`` and ``t_end``; constant outside.

    Args
    ----
    spec : dict with keys ``t_start``, ``t_end``, ``value_start``,
        ``value_end``.
    """
    t0 = float(spec["t_start"])
    t1 = float(spec["t_end"])
    v0 = float(spec["value_start"])
    v1 = float(spec["value_end"])
    if t1 <= t0:
        raise ValueError(
            f"Ramp signal: t_end ({t1}) must be greater than t_start ({t0})."
        )

    def _ramp(t: float) -> float:
        if t <= t0:
            return v0
        if t >= t1:
            return v1
        return v0 + (v1 - v0) * (t - t0) / (t1 - t0)

    return _ramp


def _make_piecewise_linear(spec: Dict[str, Any]) -> ct.Func1:
    """Piecewise-linear interpolation — wraps ``ct.Func1('tabulated', ...)``.

    Args
    ----
    spec : dict with key ``points`` — a list of ``[t, value]`` pairs.
    """
    points: List[List[float]] = spec["points"]
    if len(points) < 2:
        raise ValueError(
            f"PiecewiseLinear signal: need at least 2 points; got {len(points)}."
        )
    times = [float(p[0]) for p in points]
    values = [float(p[1]) for p in points]
    return ct.Func1("tabulated-linear", times, values)


def _make_from_csv(spec: Dict[str, Any]) -> ct.Func1:
    """Load a piecewise-linear signal from a CSV file.

    Args
    ----
    spec : dict with keys ``path``, ``time_col`` (default ``t``),
        ``value_col`` (default ``value``), ``interp`` (default ``linear``).
    """
    path = str(spec["path"])
    time_col = str(spec.get("time_col", "t"))
    value_col = str(spec.get("value_col", "value"))

    times: List[float] = []
    values: List[float] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if time_col not in row or value_col not in row:
                raise ValueError(
                    f"FromCSV signal: CSV file '{path}' is missing column "
                    f"'{time_col}' or '{value_col}'. Available: {list(row.keys())}."
                )
            times.append(float(row[time_col]))
            values.append(float(row[value_col]))
    if len(times) < 2:
        raise ValueError(
            f"FromCSV signal: need at least 2 rows in '{path}'; got {len(times)}."
        )
    return ct.Func1("tabulated-linear", times, values)


# ---------------------------------------------------------------------------
# Combinator factories (need registry to resolve prior signal IDs)
# ---------------------------------------------------------------------------


def _make_sum(
    spec: Dict[str, Any], registry: Dict[str, SignalObj]
) -> Callable[[float], float]:
    """Sum of two or more prior signals.

    Args
    ----
    spec : dict with key ``inputs`` — list of signal IDs.
    registry : already-built signals (forward references are an error).
    """
    ids: List[str] = spec["inputs"]
    sources: List[SignalObj] = []
    for sid in ids:
        if sid not in registry:
            raise ValueError(
                f"Sum signal: referenced signal '{sid}' not found. "
                "Forward references are not allowed; declare sources before combinators."
            )
        sources.append(registry[sid])

    def _sum(t: float) -> float:
        total = 0.0
        for s in sources:
            total += s(t) if callable(s) else s(t)  # type: ignore[operator]
        return total

    return _sum


def _make_gain(
    spec: Dict[str, Any], registry: Dict[str, SignalObj]
) -> Callable[[float], float]:
    """Scale a prior signal by a constant factor ``k``.

    Args
    ----
    spec : dict with keys ``input`` (signal ID) and ``k`` (float).
    registry : already-built signals.
    """
    sid = str(spec["input"])
    k = float(spec["k"])
    if sid not in registry:
        raise ValueError(
            f"Gain signal: referenced signal '{sid}' not found. "
            "Forward references are not allowed."
        )
    src = registry[sid]
    return lambda t: k * (src(t) if callable(src) else src(t))  # type: ignore[operator]


class _IntegratorSignal:
    """Stateful integrator: ``∫ input dt + x0`` using simple Euler quadrature.

    State is accumulated each time the callable is evaluated; the caller
    is responsible for consistent time stepping.
    """

    def __init__(self, source: SignalObj, x0: float) -> None:
        self._source = source
        self._x = x0
        self._t_prev: Optional[float] = None

    def __call__(self, t: float) -> float:
        if self._t_prev is None:
            self._t_prev = t
            return self._x
        dt = t - self._t_prev
        self._t_prev = t
        f_val = self._source(t) if callable(self._source) else self._source(t)  # type: ignore[operator]
        self._x += f_val * dt
        return self._x


def _make_integrator(
    spec: Dict[str, Any], registry: Dict[str, SignalObj]
) -> _IntegratorSignal:
    """Integrate a prior signal over time.

    Args
    ----
    spec : dict with keys ``input`` (signal ID) and ``x0`` (initial value,
        default 0).
    registry : already-built signals.
    """
    sid = str(spec["input"])
    x0 = float(spec.get("x0", 0.0))
    if sid not in registry:
        raise ValueError(
            f"Integrator signal: referenced signal '{sid}' not found. "
            "Forward references are not allowed."
        )
    return _IntegratorSignal(registry[sid], x0)


# ---------------------------------------------------------------------------
# Registry of source-block kinds
# ---------------------------------------------------------------------------

_PRIMITIVE_FACTORIES: Dict[str, Callable[[Dict[str, Any]], SignalObj]] = {
    "Constant": _make_constant,
    "Sine": _make_sine,
    "Gaussian": _make_gaussian,
    "Step": _make_step,
    "Ramp": _make_ramp,
    "PiecewiseLinear": _make_piecewise_linear,
    "FromCSV": _make_from_csv,
}

_COMBINATOR_KINDS = frozenset({"Sum", "Gain", "Integrator"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_signal(
    spec: Dict[str, Any], registry: Optional[Dict[str, SignalObj]] = None
) -> SignalObj:
    """Build a single signal object from a STONE source-block spec dict.

    Parameters
    ----------
    spec:
        A dict containing **exactly one** source-kind key (e.g.
        ``{"Gaussian": {...}}``) and an optional ``id`` key (ignored here).
    registry:
        Required for combinator kinds (``Sum``, ``Gain``, ``Integrator``);
        should contain all prior signals.

    Returns
    -------
    A ``ct.Func1`` or a Python callable with signature ``(t: float) -> float``.
    """
    _all_kinds = set(_PRIMITIVE_FACTORIES) | _COMBINATOR_KINDS
    kind_keys = [k for k in spec if k not in ("id",) and k in _all_kinds]
    if len(kind_keys) != 1:
        available = sorted(set(_PRIMITIVE_FACTORIES) | _COMBINATOR_KINDS)
        raise ValueError(
            f"Signal spec must contain exactly one source-kind key. "
            f"Got keys: {sorted(k for k in spec if k != 'id')}. "
            f"Available kinds: {available}."
        )
    kind = kind_keys[0]
    args = spec[kind] if isinstance(spec[kind], dict) else {}

    if kind in _PRIMITIVE_FACTORIES:
        return _PRIMITIVE_FACTORIES[kind](args)

    # Combinator
    if registry is None:
        raise ValueError(
            f"Signal kind '{kind}' is a combinator and requires a registry of "
            "prior signals to be passed."
        )
    if kind == "Sum":
        return _make_sum(args, registry)
    if kind == "Gain":
        return _make_gain(args, registry)
    if kind == "Integrator":
        return _make_integrator(args, registry)

    raise ValueError(f"Unknown signal kind '{kind}'.")  # pragma: no cover


def build_signal_registry(signals_block: List[Dict[str, Any]]) -> Dict[str, SignalObj]:
    """Build an ordered dict of named signal objects from a STONE ``signals:`` block.

    Resolution is two-pass (sources first, then combinators in declaration order)
    but the spec is processed in a single forward pass — combinators may only
    reference IDs declared earlier in the list.

    Parameters
    ----------
    signals_block:
        The list value of the top-level ``signals:`` STONE key.

    Returns
    -------
    dict mapping signal id → SignalObj (``ct.Func1`` or callable).
    """
    registry: Dict[str, SignalObj] = {}
    for entry in signals_block:
        sid = str(entry.get("id", ""))
        if not sid:
            raise ValueError(
                f"Each signal entry must have an 'id' key. Offending entry: {entry!r}."
            )
        if sid in registry:
            raise ValueError(f"Duplicate signal id '{sid}'. Signal IDs must be unique.")
        registry[sid] = build_signal(entry, registry)
    return registry
