"""Composite HDF5 (de)serialization for GUI result payloads.

This is the single, shared on-disk representation for a computed result. It is
used by both the fingerprinted result cache (:mod:`boulder.result_cache`) and
the scenario inspector (:mod:`boulder.api.routes.scenarios`) so there is exactly
**one** payload format and **one** builder.

Why composite — "best of both":

* The heavy numeric reactor state (``T``, ``P``, per-species ``X`` over an index,
  plus any per-state column such as ``t`` (time) or ``x`` (position)) is stored
  as natively-to-Cantera as possible (see the tiers below) — compact, lossless,
  no ~453-column JSON blow-up.
* Everything a case may *also* produce — Sankey links/nodes, reactor/connection
  reports, summary, generated code, node/connection overlays — is plain
  JSON-serialisable and stored verbatim in a single ``payload_json`` dataset.
  The config snapshot is **not** stored here (cache keeps it in ``meta.json``).

Per-reactor tiers, chosen by :func:`_classify_series`:

1. ``solution`` — a state series (``T``/``P``/``X`` over an index) whose species
   the mechanism can represent and whose ``X`` rows are normalised, stored as a
   Cantera :class:`~cantera.SolutionArray` group. ``Y`` is derived on load.
   **Every per-state numeric column** (``t``, ``x``, any length-``n`` array) rides
   along as a SolutionArray ``extra``. A PFR spatial profile is a state sequence
   with an ``x`` column — it is stored natively here, not dumped to JSON.
2. ``arrays`` — same shape but the mechanism can't represent it (mechanism-switch
   reactors, or non-normalised ``X``): raw HDF5 datasets (``T``/``P`` 1D, ``X``/
   ``Y`` 2D, one dataset per extra column). Binary, and **no Solution needed on
   read**.
3. ``raw`` — genuinely non-state structures: the series dict verbatim in JSON.

Non-per-state fields (flags ``is_residence``/``is_psr``/``is_spatial``, and
off-shape arrays such as ``fbs_convergence`` which is per-FBS-iteration, not
per-state) ride in the per-reactor ``meta`` of ``reactors_index`` and are merged
back on load, so the original series is reproduced exactly.

Depends only on ``cantera`` + ``h5py`` + numpy + stdlib.
"""

from __future__ import annotations

import hashlib
import json
from numbers import Real
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cantera as ct

try:
    import h5py
except ImportError as _h5py_exc:  # pragma: no cover - environment-dependent
    # h5py can fail to import in environments with mismatched HDF5 DLLs (e.g.
    # a pip-wheel Cantera inside a conda env).  The payload store is a
    # best-effort cache: degrade to "no persistence" instead of failing to
    # import (which would prevent the server from starting).
    h5py = None  # type: ignore[assignment]
    _H5PY_IMPORT_ERROR: Optional[BaseException] = _h5py_exc
else:
    _H5PY_IMPORT_ERROR = None
import numpy as np


def _require_h5py() -> None:
    """Raise a clear error when the HDF5 backend is unavailable."""
    if h5py is None:
        raise RuntimeError(
            f"h5py is unavailable, result payload persistence is disabled "
            f"(import error: {_H5PY_IMPORT_ERROR})"
        )


#: Bump when the HDF5 layout changes incompatibly (== root ``schema_version``).
PAYLOAD_SCHEMA = 1

#: Tolerance for the "X rows sum to 1" guard that gates the ``solution`` tier.
_X_SUM_TOL = 1e-6

#: Series keys handled structurally (not as generic per-state extra columns).
_STRUCTURAL_KEYS = frozenset({"T", "P", "X", "Y"})

# Cache one empty Solution per mechanism — loading a 453-species mechanism is
# the dominant cost of a restore; pay it once per process per mechanism.
_SOLUTION_CACHE: Dict[str, ct.Solution] = {}


# --------------------------------------------------------------------------- #
# Mechanism handling
# --------------------------------------------------------------------------- #
def _resolve_mechanism(mechanism: str) -> Tuple[str, str]:
    """Return ``(stored_mechanism, sha256)`` for the root attrs.

    A local mechanism file → its resolved absolute path + content hash. A
    bundled/data-path name (e.g. ``gri30.yaml``) → the bare name + empty hash.
    """
    if not mechanism:
        return "", ""
    try:
        p = Path(mechanism)
        if p.is_file():
            return str(p.resolve()), hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        pass
    return mechanism, ""


def _solution_for(mechanism: str) -> Optional[ct.Solution]:
    if not mechanism:
        return None
    sol = _SOLUTION_CACHE.get(mechanism)
    if sol is None:
        sol = ct.Solution(mechanism)
        _SOLUTION_CACHE[mechanism] = sol
    return sol


# --------------------------------------------------------------------------- #
# Series shape analysis
# --------------------------------------------------------------------------- #
def _is_numeric_list(value: Any, n: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == n
        and all(isinstance(v, Real) and not isinstance(v, bool) for v in value)
    )


def _is_state_series(series: Any) -> bool:
    """Return True when a series is state-shaped: T, P lists (equal len, >0) + X dict."""
    if not isinstance(series, dict):
        return False
    T, P, X = series.get("T"), series.get("P"), series.get("X")
    if not isinstance(T, list) or not isinstance(P, list) or not isinstance(X, dict):
        return False
    return len(T) > 0 and len(P) == len(T)


def _split_series(series: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    """Partition a state series' non-structural keys.

    Returns ``(extra_keys, meta)`` where *extra_keys* are per-state numeric
    columns of length ``n`` (e.g. ``t``, ``x``) stored natively, and *meta* is
    everything else (flags, strings, off-shape arrays like ``fbs_convergence``)
    carried verbatim in the JSON index.
    """
    n = len(series["T"])
    extra_keys: List[str] = []
    meta: Dict[str, Any] = {}
    for key, value in series.items():
        if key in _STRUCTURAL_KEYS:
            continue
        if _is_numeric_list(value, n):
            extra_keys.append(key)
        else:
            meta[key] = value
    return extra_keys, meta


def _x_matrix(series: Dict[str, Any], names: List[str]) -> np.ndarray:
    """Build an ``[n × n_species]`` X matrix aligned to *names*."""
    n = len(series["T"])
    Xd = series["X"]
    Xmat = np.zeros((n, len(names)), dtype=float)
    for j, sp in enumerate(names):
        col = Xd.get(sp)
        if col is not None:
            Xmat[:, j] = np.asarray(col, dtype=float)
    return Xmat


def _can_represent(series: Dict[str, Any], gas: Optional[ct.Solution]) -> bool:
    if gas is None:
        return False
    valid = set(gas.species_names)
    return all(sp in valid for sp in series["X"].keys())


def _x_rows_normalised(series: Dict[str, Any]) -> bool:
    """Return True when every X row sums to 1 ± tol.

    R2: don't let Cantera silently renormalise a non-normalised/diagnostic series.
    """
    cols = list(series["X"].values())
    if not cols:
        return False
    sums = np.sum(np.asarray(cols, dtype=float), axis=0)  # sum over species per index
    return bool(np.all(np.abs(sums - 1.0) <= _X_SUM_TOL))


def _classify_series(series: Any, gas: Optional[ct.Solution]) -> str:
    """Return the tier: ``solution`` | ``arrays`` | ``raw``.

    A state-shaped series (incl. spatial profiles, whose ``x`` is just another
    per-state column) is native; only genuinely non-state structures are raw.
    """
    if not _is_state_series(series):
        return "raw"
    if gas is not None and _can_represent(series, gas) and _x_rows_normalised(series):
        return "solution"
    return "arrays"


# --------------------------------------------------------------------------- #
# Numeric conversion
# --------------------------------------------------------------------------- #
def _series_to_solution_array(
    gas: ct.Solution, series: Dict[str, Any], extra_keys: List[str]
) -> ct.SolutionArray:
    T = np.asarray(series["T"], dtype=float)
    P = np.asarray(series["P"], dtype=float)
    Xmat = _x_matrix(series, gas.species_names)
    extra = {k: np.asarray(series[k], dtype=float) for k in extra_keys}
    states = ct.SolutionArray(gas, shape=(len(T),), extra=extra or None)  # type: ignore[arg-type]
    states.TPX = T, P, Xmat
    return states


def _solution_array_to_series(
    states: ct.SolutionArray, extra_keys: List[str]
) -> Dict[str, Any]:
    names = list(states.species_names)
    mole = states.X
    mass = states.Y
    out: Dict[str, Any] = {
        "T": [float(v) for v in states.T],
        "P": [float(v) for v in states.P],
        "X": {sp: [float(v) for v in mole[:, i]] for i, sp in enumerate(names)},
        "Y": {sp: [float(v) for v in mass[:, i]] for i, sp in enumerate(names)},
    }
    for key in extra_keys:
        out[key] = [float(v) for v in getattr(states, key)]
    return out


def _series_to_datasets(
    group: "h5py.Group", series: Dict[str, Any], extra_keys: List[str]
) -> None:
    """Write a state series as binary datasets (``arrays`` tier)."""
    names = list(series["X"].keys())
    group.create_dataset("T", data=np.asarray(series["T"], dtype=float))
    group.create_dataset("P", data=np.asarray(series["P"], dtype=float))
    group.create_dataset("X", data=_x_matrix(series, names))
    group.attrs["species_names"] = np.array(names, dtype=h5py.string_dtype())
    Y = series.get("Y")
    if isinstance(Y, dict) and Y:
        ynames = list(Y.keys())
        ymat = np.zeros((len(series["T"]), len(ynames)), dtype=float)
        for j, sp in enumerate(ynames):
            ymat[:, j] = np.asarray(Y[sp], dtype=float)
        group.create_dataset("Y", data=ymat)
        group.attrs["y_species_names"] = np.array(ynames, dtype=h5py.string_dtype())
    for key in extra_keys:
        group.create_dataset(f"extra__{key}", data=np.asarray(series[key], dtype=float))


def _datasets_to_series(group: "h5py.Group", extra_keys: List[str]) -> Dict[str, Any]:
    names = [_to_str(s) for s in group.attrs["species_names"]]
    Xmat = group["X"][()]
    out: Dict[str, Any] = {
        "T": [float(v) for v in group["T"][()]],
        "P": [float(v) for v in group["P"][()]],
        "X": {sp: [float(v) for v in Xmat[:, i]] for i, sp in enumerate(names)},
    }
    if "Y" in group:
        ynames = [_to_str(s) for s in group.attrs["y_species_names"]]
        Ymat = group["Y"][()]
        out["Y"] = {sp: [float(v) for v in Ymat[:, i]] for i, sp in enumerate(ynames)}
    for key in extra_keys:
        out[key] = [float(v) for v in group[f"extra__{key}"][()]]
    return out


def _to_str(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


# --------------------------------------------------------------------------- #
# Top-level write / read
# --------------------------------------------------------------------------- #
def write_payload(
    h5_path: Path,
    gui_payload: Dict[str, Any],
    mechanism: str,
    group: Optional[str] = None,
    fresh: bool = True,
) -> None:
    """Serialize *gui_payload* to a composite HDF5 file.

    Reactor series are routed to the most native tier they qualify for; the rest
    of the payload (plus a ``reactors_index``) goes into ``payload_json``.

    Parameters
    ----------
    group:
        When set, the result is written under ``<group>/…`` (one composite per
        scenario in a *collection* file). When ``None``, written at the top level
        (a single-result *cache* file).
    fresh:
        When ``True`` (and no ``group``), any existing file is replaced. For a
        collection (``group`` set) pass ``fresh=False`` to append without wiping
        previously-written scenarios.
    """
    _require_h5py()
    h5_path = Path(h5_path)
    if fresh and group is None and h5_path.exists():
        h5_path.unlink()

    prefix = f"{group}/" if group else ""

    # Shallow-copy the top level and pop the heavy series — never deepcopy the
    # big X arrays (P3); they are routed straight into HDF5.
    lean = dict(gui_payload)
    series_map: Dict[str, Any] = lean.pop("reactors_series", None) or {}

    gas = _solution_for(mechanism)

    index: Dict[str, Dict[str, Any]] = {}
    solution_groups: List[Tuple[str, ct.SolutionArray]] = []
    array_series: List[Tuple[str, Dict[str, Any], List[str]]] = []
    for i, (rid, series) in enumerate(series_map.items()):
        kind = _classify_series(series, gas)
        if kind == "raw":
            index[rid] = {"kind": "raw", "series": _jsonify(series)}
            continue
        rgroup = f"r{i}"  # stored relative; prefixed on disk/read
        extra_keys, meta = _split_series(series)
        index[rid] = {
            "kind": kind,
            "group": rgroup,
            "extra_keys": extra_keys,
            "meta": _jsonify(meta),
        }
        if kind == "solution":
            solution_groups.append(
                (rgroup, _series_to_solution_array(gas, series, extra_keys))  # type: ignore[arg-type]
            )
        else:
            array_series.append((rgroup, series, extra_keys))

    lean["reactors_index"] = index
    blob = json.dumps(lean, ensure_ascii=False, separators=(",", ":"))

    # 1) Cantera writes its SolutionArray groups first and fully, before any
    #    h5py handle touches the file (R4: no interleaved open handles).
    #    overwrite=True is per-group: in a collection it only replaces this
    #    scenario's groups, never sibling scenarios.
    for idx, (rgroup, states) in enumerate(solution_groups):
        states.save(
            str(h5_path), name=f"{prefix}{rgroup}", overwrite=(bool(group) or idx == 0)
        )

    # 2) Then a single h5py session for array groups + the JSON blob + attrs.
    mode = "r+" if h5_path.exists() else "w"
    stored_mech, sha = _resolve_mechanism(mechanism)
    with h5py.File(str(h5_path), mode) as handle:
        node = handle.require_group(group) if group else handle
        for rgroup, series, extra_keys in array_series:
            full = f"{prefix}{rgroup}"
            if full in handle:
                del handle[full]
            _series_to_datasets(handle.create_group(full), series, extra_keys)
        if "payload_json" in node:
            del node["payload_json"]
        node.create_dataset("payload_json", data=blob)
        node.attrs["schema_version"] = PAYLOAD_SCHEMA
        node.attrs["mechanism"] = stored_mech
        node.attrs["mechanism_sha256"] = sha
        node.attrs["mechanism_name"] = Path(mechanism).name if mechanism else ""


def read_payload(
    h5_path: Path,
    mechanism_override: Optional[str] = None,
    group: Optional[str] = None,
) -> Dict[str, Any]:
    """Inverse of :func:`write_payload` → the full ``gui_payload``.

    Rehydrates ``reactors_series`` by tier and merges each reactor's ``meta``.
    ``group`` selects one scenario's composite from a collection file. Raises on
    restore failure; callers decide miss-vs-error (R1).
    """
    _require_h5py()
    h5_path = Path(h5_path)
    prefix = f"{group}/" if group else ""
    with h5py.File(str(h5_path), "r") as handle:
        node = handle[group] if group else handle
        raw = node["payload_json"][()]
        mechanism = (
            mechanism_override
            or _to_str(node.attrs.get("mechanism", ""))
            or _to_str(handle.attrs.get("mechanism", ""))
        )
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    gui = json.loads(raw)

    index = gui.pop("reactors_index", None)
    if index is None:
        return gui  # defensive: nothing to rehydrate

    needs_solution = any(e.get("kind") == "solution" for e in index.values())
    gas = _solution_for(mechanism) if needs_solution else None

    series: Dict[str, Any] = {}
    array_entries = []
    for rid, entry in index.items():
        kind = entry.get("kind")
        if kind == "raw":
            series[rid] = entry["series"]
        elif kind == "solution":
            assert gas is not None  # the solution tier implies the mechanism loaded
            states = ct.SolutionArray(gas)
            states.restore(str(h5_path), name=f"{prefix}{entry['group']}")
            rebuilt = _solution_array_to_series(states, entry.get("extra_keys") or [])
            rebuilt.update(entry.get("meta") or {})
            series[rid] = rebuilt
        else:  # arrays — read together in one h5py session below
            array_entries.append((rid, entry))

    if array_entries:
        with h5py.File(str(h5_path), "r") as handle:
            for rid, entry in array_entries:
                rebuilt = _datasets_to_series(
                    handle[f"{prefix}{entry['group']}"], entry.get("extra_keys") or []
                )
                rebuilt.update(entry.get("meta") or {})
                series[rid] = rebuilt

    gui["reactors_series"] = series
    return gui


def _jsonify(value: Any) -> Any:
    """Best-effort JSON-safe coercion (numpy scalars/arrays) for raw/meta blobs."""
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


# --------------------------------------------------------------------------- #
# Shared builder (scenario inspector)
# --------------------------------------------------------------------------- #
def gui_payload_from_solution_array(
    states: ct.SolutionArray,
    reactor_id: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a full ``SimulationResults`` gui_payload from one SolutionArray.

    Shared by the scenario inspector so a restored trajectory renders through
    the exact same shape as a cached live run. ``extra`` may override/augment
    derived fields (e.g. Sankey for a richer case).
    """
    rebuilt = _solution_array_to_series(states, ["t"])
    rebuilt["is_residence"] = True
    series = {reactor_id: rebuilt}
    payload: Dict[str, Any] = {
        "status": "complete",
        "is_running": False,
        "is_complete": True,
        "error_message": None,
        "times": rebuilt["t"],
        "reactors_series": series,
        "reactor_reports": {},
        "connection_reports": {},
        "code_str": "",
        "summary": [],
        "sankey_links": None,
        "sankey_nodes": None,
        "elapsed_time": None,
        "updated_nodes": None,
        "updated_connections": None,
    }
    if extra:
        payload.update(extra)
    return payload
