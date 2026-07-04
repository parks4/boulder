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

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import h5py
except ImportError:  # pragma: no cover - environment-dependent
    # Scenario stores are HDF5 files; without a working h5py the routes report
    # "no scenarios" instead of preventing the whole API from importing.
    h5py = None  # type: ignore[assignment]
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
    """List scenario composites — top-level groups holding a ``payload_json``."""
    entries: List[Dict[str, Any]] = []
    with h5py.File(str(h5_path), "r") as handle:
        for name, node in handle.items():
            if not isinstance(node, h5py.Group) or "payload_json" not in node:
                continue
            entry = {key: _to_py(val) for key, val in node.attrs.items()}
            entry["id"] = name
            entries.append(entry)
    # Sort by explicit order, else by initial temperature, else by id.
    entries.sort(key=lambda e: (e.get("order", e.get("t0_K", 0.0)), e["id"]))
    return entries


@router.get("")
async def list_scenarios(request: Request) -> Dict[str, Any]:
    """List the scenarios in the active store (fast — reads attrs only)."""
    store = _store_path(request)
    if h5py is None or store is None or not store.is_file():
        return {"available": False, "scenarios": []}
    root = _root_attrs(store)
    return {
        "available": True,
        "store": store.name,
        "mechanism": root.get("mechanism_name"),
        "reactor_mode": root.get("reactor_mode"),
        "created_at": root.get("created_at"),
        "scenarios": _scenario_entries(store),
    }


@router.get("/{scenario_id}")
async def get_scenario(scenario_id: str, request: Request) -> Dict[str, Any]:
    """Return one scenario's composite payload (multi-reactor, reports, Sankey)."""
    if h5py is None:
        raise HTTPException(status_code=503, detail="h5py unavailable")
    store = _store_path(request)
    if store is None or not store.is_file():
        raise HTTPException(status_code=404, detail="No scenario store available")

    entries = {e["id"]: e for e in _scenario_entries(store)}
    if scenario_id not in entries:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario_id!r}")

    root = _root_attrs(store)
    mechanism = str(root.get("mechanism") or root.get("mechanism_name") or "")
    try:
        from ...payload_store import read_payload

        return read_payload(store, mechanism_override=mechanism, group=scenario_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore scenario {scenario_id!r}: {exc}",
        ) from exc


# --------------------------------------------------------------------------- #
# Scenario-focus channel — a generic remote-control seam.
#
# An external process (e.g. a separate result dashboard) can ask the open GUI to
# load and visualise a given scenario id by POSTing to ``/focus``; every browser
# tab subscribed to ``/focus/stream`` receives the id and loads it. The push is
# in-process (a set of asyncio queues on ``app.state``); it carries only a
# scenario id, so it stays domain-neutral.
# --------------------------------------------------------------------------- #


class FocusRequest(BaseModel):
    scenario_id: str


def _focus_subscribers(request: Request) -> "set[asyncio.Queue]":
    """Return the live set of SSE subscriber queues (created on first use)."""
    subs = getattr(request.app.state, "scenario_focus_subscribers", None)
    if subs is None:
        subs = set()
        request.app.state.scenario_focus_subscribers = subs
    return subs


def _focus_event(scenario_id: str) -> str:
    """One SSE ``focus`` event carrying the scenario id."""
    return f"event: focus\ndata: {json.dumps({'scenario_id': scenario_id})}\n\n"


@router.post("/focus")
async def focus_scenario(req: FocusRequest, request: Request) -> Dict[str, Any]:
    """Tell every subscribed GUI tab to load scenario ``scenario_id`` (live)."""
    if h5py is None:
        raise HTTPException(status_code=503, detail="h5py unavailable")
    store = _store_path(request)
    if store is None or not store.is_file():
        raise HTTPException(status_code=404, detail="No scenario store available")
    known = {e["id"] for e in _scenario_entries(store)}
    if req.scenario_id not in known:
        raise HTTPException(
            status_code=404, detail=f"Unknown scenario {req.scenario_id!r}"
        )

    request.app.state.focused_scenario = req.scenario_id
    for queue in list(_focus_subscribers(request)):
        try:
            queue.put_nowait(req.scenario_id)
        except asyncio.QueueFull:  # pragma: no cover — unbounded queues
            pass
    return {"ok": True, "scenario_id": req.scenario_id}


@router.get("/focus/stream")
async def focus_stream(request: Request) -> StreamingResponse:
    """SSE stream of scenario-focus events for the GUI to follow.

    Emits the current focus (if any) immediately so a late-joining tab syncs,
    then one ``focus`` event per :func:`focus_scenario` call; periodic comments
    keep the connection alive.
    """
    subs = _focus_subscribers(request)
    queue: asyncio.Queue = asyncio.Queue()
    subs.add(queue)
    current = getattr(request.app.state, "focused_scenario", None)

    async def gen():
        try:
            if current:
                yield _focus_event(current)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    scenario_id = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _focus_event(scenario_id)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # SSE comment — no event fired
        finally:
            subs.discard(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
