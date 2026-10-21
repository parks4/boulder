"""Read stored simulation results from anywhere: a Python API over the result store.

A result store (:mod:`boulder.scenario_store`) holds one HDF5 file per run-set
entry. Each reactor trajectory inside is a native Cantera ``SolutionArray``
group; Boulder adds the run-set inputs and scalars as attributes and a JSON
payload. This module opens such a store without the GUI and without the
original config::

    from boulder.results import open_results

    rs = open_results("path/to/store_dir")          # or the STONE YAML
    rs.table()                                     # one row per scenario (pandas)
    sc = rs.select(temperature=1200.0)             # or rs["<scenario id>"]
    sc.states("r0")                                # cantera.SolutionArray, with "t"
    sc.series("r0", "t", "T", "X:CH4")             # plain numpy arrays
    rs.plot("r0", "T")                             # one line per scenario

Nothing is re-solved: :meth:`Scenario.states` rebuilds Cantera states from the
stored arrays, so every Cantera property (enthalpies, rates, equilibrium, ...)
is available on them.

Opening "from anywhere"
-----------------------
The store stamps each entry with the absolute path of the config that wrote it,
and the GUI only serves entries whose stamp matches its config. This reader
ignores that stamp, so a copied or moved store opens as is.

Rebuilding states needs the mechanism. It is resolved in this order: the
``mechanism`` argument, the absolute path stored in the entry, then
``mechanism_name`` in each ``search_path`` directory. A local mechanism file is
stored with its SHA-256; a resolved file whose hash differs raises
:class:`MechanismMismatchError` (``allow_mismatch=True`` downgrades it to a
warning). Mechanisms found on Cantera's own data path (e.g. ``gri30.yaml``) are
stored without a hash and are not checked.
"""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

import cantera as ct
import h5py
import numpy as np

from . import scenario_store
from .runset import store_entry_path

PathLike = Union[str, Path]

#: Prefix of the run-set input attrs written for each entry (``in.<node>.<prop>``).
INPUT_PREFIX = "in."


class MechanismMismatchError(ValueError):
    """The resolved mechanism file is not the one the results were computed with."""


def open_results(
    path: PathLike,
    *,
    mechanism: Optional[PathLike] = None,
    search_path: Sequence[PathLike] = (),
    allow_mismatch: bool = False,
) -> "ScenarioSet":
    """Open a result store, given its directory or the STONE config that wrote it.

    Parameters
    ----------
    path :
        A store directory (``*.h5`` entries), or a ``.yaml``/``.yml`` config, whose
        store is located as the sweep runner locates it.
    mechanism :
        Mechanism file to use for every entry, overriding the stored path.
    search_path :
        Directories searched for the stored ``mechanism_name``.
    allow_mismatch :
        Warn instead of raising when a mechanism's SHA-256 differs from the stored one.
    """
    p = Path(path)
    if p.suffix.lower() in {".yaml", ".yml"}:
        store_dir = _store_dir_for_config(p)
    else:
        store_dir = p
    if not store_dir.is_dir():
        raise FileNotFoundError(f"result store not found: {store_dir}")
    return ScenarioSet(
        store_dir,
        mechanism=mechanism,
        search_path=search_path,
        allow_mismatch=allow_mismatch,
    )


def _store_dir_for_config(config_path: Path) -> Path:
    from .runset import load_yaml_with_inheritance, resolve_store_dir  # noqa: PLC0415

    store_dir = resolve_store_dir(load_yaml_with_inheritance(config_path), config_path)
    if store_dir is None:  # pragma: no cover - only for an empty config path
        raise FileNotFoundError(f"no result store for {config_path}")
    return store_dir


class ScenarioSet(Mapping[str, "Scenario"]):
    """All usable entries of one result store, keyed by scenario id, in run-set order."""

    def __init__(
        self,
        store_dir: Path,
        *,
        mechanism: Optional[PathLike] = None,
        search_path: Sequence[PathLike] = (),
        allow_mismatch: bool = False,
    ) -> None:
        self.store_dir = Path(store_dir)
        self._mechanism = Path(mechanism) if mechanism else None
        self._search_path = [Path(d) for d in search_path]
        self._allow_mismatch = allow_mismatch
        self._solutions: Dict[str, ct.Solution] = {}
        # identity="" : read every complete entry, whatever config wrote it.
        entries = scenario_store.list_entries(self.store_dir, identity="")
        self._scenarios = {
            str(e["id"]): Scenario(self, str(e["id"]), e) for e in entries
        }

    def __getitem__(self, scenario_id: str) -> "Scenario":
        return self._scenarios[scenario_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._scenarios)

    def __len__(self) -> int:
        return len(self._scenarios)

    def __repr__(self) -> str:
        return f"ScenarioSet({str(self.store_dir)!r}, {len(self)} scenarios)"

    def table(self) -> Any:
        """Return a pandas DataFrame: one row per scenario, inputs and stored scalars.

        Bookkeeping attrs (fingerprints, mechanism, version) are left out.
        """
        import pandas as pd  # noqa: PLC0415 - optional dependency

        rows = []
        for sc in self.values():
            row: Dict[str, Any] = {"id": sc.id, "label": sc.label}
            row.update(sc.inputs)
            row.update(sc.scalars)
            rows.append(row)
        return pd.DataFrame(rows).set_index("id")

    def select(self, **inputs: Any) -> "Scenario":
        """Return the one scenario whose inputs match every ``name=value`` given.

        ``name`` is either a full input attr (``in.r0.temperature``, written with
        ``__`` for dots) or its last component (``temperature``) when unique.
        Floats are compared with :func:`math.isclose`.
        """
        matches = [sc for sc in self.values() if sc.matches(**inputs)]
        if len(matches) != 1:
            ids = [sc.id for sc in matches]
            raise KeyError(f"{len(matches)} scenarios match {inputs}: {ids}")
        return matches[0]

    def plot(self, reactor: str, var: str, ax: Any = None) -> Any:
        """Plot ``var`` against time for every scenario on one axis; return the axis."""
        for sc in self.values():
            ax = sc.plot(reactor, var, ax=ax, label=sc.label)
        ax.legend(frameon=False)
        return ax

    # -- mechanism ----------------------------------------------------------
    def _solution(self, attrs: Dict[str, Any]) -> ct.Solution:
        path = self._resolve_mechanism(attrs)
        if path not in self._solutions:
            from .ctutils import derive_solution, load_solution  # noqa: PLC0415

            self._solutions[path] = derive_solution(load_solution(path), kinetics=True)
        return self._solutions[path]

    def _resolve_mechanism(self, attrs: Dict[str, Any]) -> str:
        stored = str(attrs.get("mechanism") or "")
        name = str(attrs.get("mechanism_name") or Path(stored).name)
        sha = str(attrs.get("mechanism_sha256") or "")
        candidates: List[Path] = []
        if self._mechanism is not None:
            candidates.append(self._mechanism)
        if stored:
            candidates.append(Path(stored))
        candidates += [d / name for d in self._search_path]
        for cand in candidates:
            if cand.is_file():
                self._check_sha(cand, sha)
                return str(cand.resolve())
        if not sha and name:
            return name  # bundled mechanism: Cantera finds it on its data path
        searched = ", ".join(str(c) for c in candidates) or "(nothing)"
        raise FileNotFoundError(
            f"mechanism {name!r} not found (searched {searched}); pass mechanism= or search_path="
        )

    def _check_sha(self, path: Path, expected: str) -> None:
        if not expected:
            return
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual == expected:
            return
        msg = (
            f"{path} has SHA-256 {actual[:12]}..., but the results were computed with "
            f"{expected[:12]}...: not the same mechanism file"
        )
        if not self._allow_mismatch:
            raise MechanismMismatchError(msg)
        warnings.warn(msg, stacklevel=4)


class Scenario:
    """One stored run: its inputs, scalars and per-reactor trajectories."""

    def __init__(
        self, owner: ScenarioSet, scenario_id: str, attrs: Dict[str, Any]
    ) -> None:
        self._owner = owner
        self.id = scenario_id
        self.attrs = attrs
        self.path = store_entry_path(owner.store_dir, scenario_id)
        self._index: Optional[Dict[str, Any]] = None

    def __repr__(self) -> str:
        return f"Scenario({self.id!r})"

    @property
    def label(self) -> str:
        return str(self.attrs.get("label") or self.id)

    @property
    def inputs(self) -> Dict[str, Any]:
        """Run-set inputs of this scenario, ``{"in.<node>.<prop>": value}``."""
        return {k: v for k, v in self.attrs.items() if k.startswith(INPUT_PREFIX)}

    @property
    def scalars(self) -> Dict[str, Any]:
        """Stored scalar results (attrs that are neither inputs nor bookkeeping)."""
        skip = scenario_store.NON_KPI_ATTRS | {"id"}
        return {
            k: v
            for k, v in self.attrs.items()
            if k not in skip and not k.startswith(INPUT_PREFIX)
        }

    @property
    def reactors(self) -> List[str]:
        """Ids of the reactors with a stored trajectory."""
        return list(self._reactor_index())

    def matches(self, **inputs: Any) -> bool:
        """Whether every ``name=value`` matches an input (see :meth:`ScenarioSet.select`)."""
        for name, value in inputs.items():
            key = name.replace("__", ".")
            hits = [k for k in self.inputs if k == key or k.rsplit(".", 1)[-1] == key]
            if len(hits) != 1:
                return False
            stored = self.inputs[hits[0]]
            if isinstance(value, (int, float)) and isinstance(stored, (int, float)):
                if not math.isclose(
                    float(stored), float(value), rel_tol=1e-9, abs_tol=1e-12
                ):
                    return False
            elif stored != value:
                return False
        return True

    def states(self, reactor: str) -> ct.SolutionArray:
        """Return the reactor's trajectory as a Cantera ``SolutionArray`` (nothing is re-solved).

        Extra columns stored with it (``t``, ...) are attributes of the array.
        """
        entry = self._reactor_entry(reactor)
        if entry.get("kind") != "solution":
            raise ValueError(
                f"reactor {reactor!r} is stored as {entry.get('kind')!r}, not as Cantera states; "
                "use series()"
            )
        gas = self._owner._solution(self.attrs)
        arr = ct.SolutionArray(gas, extra=list(entry.get("extra_keys") or []))
        arr.restore(str(self.path), name=entry["group"])
        return arr

    def series(self, reactor: str, *names: str) -> Dict[str, np.ndarray]:
        """Return named columns as arrays.

        ``name`` is ``"X:<species>"`` / ``"Y:<species>"`` for a mole / mass fraction,
        or any ``SolutionArray`` attribute (``"t"``, ``"T"``, ``"P"``, ``"cp_mass"``...).
        Reactors stored without Cantera states support their stored keys only.
        """
        entry = self._reactor_entry(reactor)
        out: Dict[str, np.ndarray] = {}
        if entry.get("kind") == "solution":
            arr = self.states(reactor)
            for name in names:
                if name[:2] in {"X:", "Y:"}:
                    out[name] = np.asarray(getattr(arr(name[2:]), name[0])[:, 0])
                else:
                    out[name] = np.asarray(getattr(arr, name))
            return out
        from .payload_store import read_payload  # noqa: PLC0415

        raw = read_payload(self.path)["reactors_series"][reactor]
        for name in names:
            if name[:2] in {"X:", "Y:"}:
                out[name] = np.asarray(raw[name[0]][name[2:]], dtype=float)
            else:
                out[name] = np.asarray(raw[name], dtype=float)
        return out

    def plot(
        self, reactor: str, var: str, ax: Any = None, label: Optional[str] = None
    ) -> Any:
        """Plot ``var`` (a :meth:`series` name) against time; return the axis."""
        import matplotlib.pyplot as plt  # noqa: PLC0415 - optional dependency

        if ax is None:
            _, ax = plt.subplots()
        cols = self.series(reactor, "t", var)
        ax.plot(cols["t"], cols[var], label=label or self.label)
        ax.set_xlabel("t [s]")
        ax.set_ylabel(var)
        return ax

    # -- payload index ------------------------------------------------------
    def _reactor_index(self) -> Dict[str, Any]:
        if self._index is None:
            with h5py.File(str(self.path), "r") as handle:
                raw = handle["payload_json"][()]
            blob = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            self._index = blob.get("reactors_index") or {}
        return self._index

    def _reactor_entry(self, reactor: str) -> Dict[str, Any]:
        index = self._reactor_index()
        if reactor not in index:
            raise KeyError(
                f"no reactor {reactor!r} in {self.id}; stored: {sorted(index)}"
            )
        return dict(index[reactor])
