"""Scenario inspector API: list and load precomputed reactor trajectories.

Reads a self-describing HDF5 *scenario store* — one Cantera
:class:`~cantera.SolutionArray` per scenario (named HDF5 group), with per-group
and root attributes — and serves each scenario as a ``SimulationResults``-shaped
payload that the frontend renders through ``setResults`` (the same path used for
a cached solve). All scenarios share one network topology, so the GUI only swaps
result data and never rebuilds the graph.

Store location: ``app.state.scenario_store_path`` (set by the lifespan from the
preloaded config's ``metadata.extra.scenario_store``, or ``BOULDER_SCENARIO_STORE``).

This module depends only on ``cantera`` + ``h5py`` + stdlib (no host package); the
HDF5 schema is the contract between producer and GUI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import cantera as ct
import h5py
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def _store_path(request: Request) -> Optional[Path]:
    raw = getattr(request.app.state, "scenario_store_path", None)
    return Path(raw) if raw else None


def _to_py(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            return value
    return value


def _root_attrs(h5_path: Path) -> Dict[str, Any]:
    with h5py.File(str(h5_path), "r") as handle:
        return {key: _to_py(val) for key, val in handle.attrs.items()}


def _scenario_entries(h5_path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    with h5py.File(str(h5_path), "r") as handle:
        for name, node in handle.items():
            if not isinstance(node, h5py.Group) or "t0_K" not in node.attrs:
                continue
            entry = {key: _to_py(val) for key, val in node.attrs.items()}
            entry["id"] = name
            entries.append(entry)
    entries.sort(key=lambda e: e.get("t0_K", 0.0))
    return entries


def _solution_for(request: Request, mechanism: str) -> ct.Solution:
    """Return a cached empty Solution per mechanism (load paid once)."""
    cache = getattr(request.app.state, "_scenario_solutions", None)
    if cache is None:
        cache = {}
        request.app.state._scenario_solutions = cache
    if mechanism not in cache:
        cache[mechanism] = ct.Solution(mechanism)
    return cache[mechanism]


def _reactors_series(states: ct.SolutionArray, reactor_id: str) -> Dict[str, Any]:
    names = list(states.species_names)
    mole = states.X
    mass = states.Y
    return {
        reactor_id: {
            "T": [float(v) for v in states.T],
            "P": [float(v) for v in states.P],
            "X": {sp: [float(v) for v in mole[:, i]] for i, sp in enumerate(names)},
            "Y": {sp: [float(v) for v in mass[:, i]] for i, sp in enumerate(names)},
            "is_residence": True,
            "t": [float(v) for v in states.t],
        }
    }


def _gui_payload(states: ct.SolutionArray, reactor_id: str) -> Dict[str, Any]:
    series = _reactors_series(states, reactor_id)
    return {
        "status": "complete",
        "is_running": False,
        "is_complete": True,
        "error_message": None,
        "times": series[reactor_id]["t"],
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


@router.get("")
async def list_scenarios(request: Request) -> Dict[str, Any]:
    """List the scenarios in the active store (fast — reads attrs only)."""
    store = _store_path(request)
    if store is None or not store.is_file():
        return {"available": False, "scenarios": []}
    root = _root_attrs(store)
    return {
        "available": True,
        "store": store.name,
        "mechanism": root.get("mechanism_name"),
        "reactor_mode": root.get("reactor_mode"),
        "scenarios": _scenario_entries(store),
    }


@router.get("/{scenario_id}")
async def get_scenario(scenario_id: str, request: Request) -> Dict[str, Any]:
    """Restore one scenario's SolutionArray and return it as a results payload."""
    store = _store_path(request)
    if store is None or not store.is_file():
        raise HTTPException(status_code=404, detail="No scenario store available")

    entries = {e["id"]: e for e in _scenario_entries(store)}
    if scenario_id not in entries:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario_id!r}")

    root = _root_attrs(store)
    mechanism = str(root.get("mechanism") or root.get("mechanism_name") or "")
    reactor_id = str(root.get("reactor_id") or "reactor")
    try:
        gas = _solution_for(request, mechanism)
        states = ct.SolutionArray(gas)
        states.restore(str(store), name=scenario_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore scenario {scenario_id!r}: {exc}",
        ) from exc

    return _gui_payload(states, reactor_id)
