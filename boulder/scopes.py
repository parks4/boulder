"""Declarative scope / observer implementation for Boulder's causal layer (Phase C).

A *scope* in the STONE ``scopes:`` block is a named observer that records
the time-evolution of one variable path in the reactor network.

Usage::

    from boulder.scopes import ScopeRecorder, resolve_scope_variable

    recorder = ScopeRecorder(scopes_block, converter)
    # Inside the solve loop, after each step:
    recorder.record(t)
    # After the solve:
    df_dict = recorder.to_dataframes()      # dict[str, pd.DataFrame]
    recorder.flush_csv()                    # write files where file: is set
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Variable path resolver
# ---------------------------------------------------------------------------


def resolve_scope_variable(
    variable: str,
    converter: Any,
) -> Callable[[], float]:
    """Return a zero-argument callable that reads *variable* from the network.

    Supported variable paths:

    - ``nodes.<id>.T``  — reactor temperature (K)
    - ``nodes.<id>.P``  — reactor pressure (Pa)
    - ``nodes.<id>.V``  — reactor volume (m³, for reactors that support it)
    - ``nodes.<id>.mass``  — reactor mass (kg)
    - ``nodes.<id>.X[<species>]``  — mole fraction of a species
    - ``nodes.<id>.Y[<species>]``  — mass fraction of a species
    - ``connections.<id>.mass_flow_rate``  — MFC mass flow rate (kg/s)

    Parameters
    ----------
    variable:
        Dotted path string.
    converter:
        A :class:`~boulder.cantera_converter.DualCanteraConverter` with
        populated ``reactors`` and ``connections``.

    Returns
    -------
    Callable that returns ``float`` when called.

    Raises
    ------
    ValueError
        If the path is not supported or the referenced ID does not exist.
    """
    parts = variable.split(".")
    if len(parts) < 3:
        raise ValueError(
            f"Scope variable '{variable}' must be a dotted path with at least 3 parts "
            "(e.g. 'nodes.r1.T'). Supported: nodes.<id>.<attr> and "
            "connections.<id>.mass_flow_rate."
        )

    kind = parts[0]
    item_id = parts[1]
    attr = ".".join(parts[2:])

    if kind == "nodes":
        reactor = converter.reactors.get(item_id)
        if reactor is None:
            raise ValueError(
                f"Scope variable '{variable}': node '{item_id}' not found. "
                f"Available: {sorted(converter.reactors)}."
            )

        # Species mole/mass fraction: X[species] or Y[species]
        if attr.startswith("X[") and attr.endswith("]"):
            species = attr[2:-1]

            def _read_mole_fraction(_r=reactor, _s=species) -> float:
                try:
                    idx = _r.thermo.species_index(_s)
                    return float(_r.thermo.X[idx])
                except Exception:
                    return float("nan")

            return _read_mole_fraction

        if attr.startswith("Y[") and attr.endswith("]"):
            species = attr[2:-1]

            def _read_mass_fraction(_r=reactor, _s=species) -> float:
                try:
                    idx = _r.thermo.species_index(_s)
                    return float(_r.thermo.Y[idx])
                except Exception:
                    return float("nan")

            return _read_mass_fraction

        # Scalar reactor attributes
        _REACTOR_ATTRS = {
            "T": lambda r: float(r.T),
            "P": lambda r: float(r.thermo.P),
            "V": lambda r: float(r.volume) if hasattr(r, "volume") else float("nan"),
            "mass": lambda r: float(r.mass) if hasattr(r, "mass") else float("nan"),
        }
        if attr in _REACTOR_ATTRS:
            getter: Callable[[Any], float] = _REACTOR_ATTRS[attr]
            _r_bound = reactor

            def _read_reactor_attr() -> float:
                return getter(_r_bound)

            return _read_reactor_attr

        raise ValueError(
            f"Scope variable '{variable}': unsupported node attribute '{attr}'. "
            f"Supported: T, P, V, mass, X[species], Y[species]."
        )

    if kind == "connections":
        device = converter.connections.get(item_id)
        if device is None:
            raise ValueError(
                f"Scope variable '{variable}': connection '{item_id}' not found. "
                f"Available: {sorted(converter.connections)}."
            )
        if attr == "mass_flow_rate":
            # mass_flow_rate read requires an initialised network; we guard with try/except
            def _read_mdot(_d=device) -> float:
                try:
                    return float(_d.mass_flow_rate)
                except Exception:
                    return float("nan")

            return _read_mdot

        raise ValueError(
            f"Scope variable '{variable}': unsupported connection attribute '{attr}'. "
            "Supported: mass_flow_rate."
        )

    raise ValueError(
        f"Scope variable '{variable}': unrecognised kind '{kind}'. "
        "Supported prefixes: 'nodes', 'connections'."
    )


# ---------------------------------------------------------------------------
# Scope recorder
# ---------------------------------------------------------------------------


class ScopeRecorder:
    """Records time-series data for a list of scope definitions.

    Parameters
    ----------
    scopes_block:
        The list value of the top-level ``scopes:`` STONE key.
    converter:
        A fully-built :class:`~boulder.cantera_converter.DualCanteraConverter`.
    """

    def __init__(
        self,
        scopes_block: Optional[List[Dict[str, Any]]],
        converter: Any,
    ) -> None:
        self._scopes: List[Dict[str, Any]] = scopes_block or []
        self._getters: Dict[str, Callable[[], float]] = {}
        self._data: Dict[str, List[Tuple[float, float]]] = {}
        self._every: Dict[str, int] = {}
        self._file: Dict[str, Optional[str]] = {}
        self._step_count: Dict[str, int] = {}

        for scope in self._scopes:
            var = scope.get("variable", "")
            if not var:
                logger.warning("Scope entry missing 'variable' key; skipping.")
                continue
            try:
                getter = resolve_scope_variable(var, converter)
            except ValueError as exc:
                logger.warning("Scope '%s' skipped: %s", var, exc)
                continue
            self._getters[var] = getter
            self._data[var] = []
            self._every[var] = int(scope.get("every", 1))
            self._file[var] = scope.get("file") or None
            self._step_count[var] = 0

    def record(self, t: float) -> None:
        """Sample all active scopes at time *t*.

        Call this after each integrator step or chunk.
        """
        for var, getter in self._getters.items():
            stride = self._every.get(var, 1)
            self._step_count[var] = self._step_count.get(var, 0) + 1
            if self._step_count[var] % stride == 0:
                try:
                    value = getter()
                except Exception as exc:
                    logger.debug("Scope '%s' read error at t=%g: %s", var, t, exc)
                    value = float("nan")
                self._data[var].append((t, value))

    def to_dataframes(self) -> Dict[str, Any]:
        """Return scope data as a dict of ``pandas.DataFrame`` objects.

        Each DataFrame has columns ``t`` (time in seconds) and ``value``.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "BoulderRunner.scopes requires pandas. "
                "Install it with: pip install pandas"
            ) from exc
        result: Dict[str, Any] = {}
        for var, rows in self._data.items():
            if rows:
                ts_list, vals_list = zip(*rows)
                ts: Sequence[float] = list(ts_list)
                vals = list(vals_list)
            else:
                ts, vals = [], []
            result[var] = pd.DataFrame({"t": list(ts), "value": list(vals)})
        return result

    def flush_csv(self) -> None:
        """Write per-scope CSV files for scopes that have a ``file:`` path set."""
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("ScopeRecorder.flush_csv requires pandas.") from exc
        for var, rows in self._data.items():
            path = self._file.get(var)
            if path is None:
                continue
            if rows:
                ts_list, vals_list = zip(*rows)
                ts = list(ts_list)
                vals = list(vals_list)
            else:
                ts, vals = [], []
            df = pd.DataFrame({"t": ts, "value": vals})
            df.to_csv(path, index=False)
            logger.info("Scope '%s' flushed to '%s' (%d rows).", var, path, len(df))

    @property
    def variables(self) -> List[str]:
        """List of active scope variable paths."""
        return list(self._getters.keys())

    @property
    def raw_data(self) -> Dict[str, List[Tuple[float, float]]]:
        """Raw (t, value) tuples for each scope variable."""
        return dict(self._data)
