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


def _purge_cached_group(store: Optional[Path], scenario_id: str) -> bool:
    """Remove *scenario_id*'s cached trajectory from the store, if present.

    Best-effort: the scenario's *definition* is already deleted by the caller
    by the time this runs, so a missing/unreadable store is not an error here
    — there is just nothing left to purge. Returns whether a group was
    actually removed (surfaced to the frontend so "Delete" can honestly say
    whether it also cleared a cached result).
    """
    if h5py is None or store is None or not store.is_file():
        return False
    try:
        with h5py.File(str(store), "a") as handle:
            if scenario_id in handle:
                del handle[scenario_id]
                return True
    except OSError:
        return False
    return False


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


def _authored_scenario_ids(request: Request) -> List[str]:
    """Return every scenario id currently in the config's `scenarios:` mapping.

    Unlike the HDF5-derived list below (only scenarios a sweep has actually
    computed), this reflects the source YAML directly — so a scenario that
    was just created/edited but never swept still shows up, e.g. as a clone
    base in the Add Scenario modal.
    """
    cfg_path = _config_path(request)
    if cfg_path is None or not cfg_path.is_file():
        return []
    from ...scenario_editor import list_scenario_ids

    return list_scenario_ids(cfg_path)


@router.get("")
async def list_scenarios(request: Request) -> Dict[str, Any]:
    """List the scenarios in the active store (fast — reads attrs only)."""
    store = _store_path(request)
    authored_ids = _authored_scenario_ids(request)
    if h5py is None or store is None or not store.is_file():
        return {"available": False, "scenarios": [], "authored_ids": authored_ids}
    root = _root_attrs(store)
    return {
        "available": True,
        "store": store.name,
        "mechanism": root.get("mechanism_name"),
        "reactor_mode": root.get("reactor_mode"),
        "created_at": root.get("created_at"),
        "scenarios": _scenario_entries(store),
        "authored_ids": authored_ids,
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
# Scenario authoring — create/edit/delete a ``scenarios:`` overlay on disk.
#
# Unlike the read routes above (which serve precomputed HDF5 trajectories),
# these operate on the *source* config file (``app.state.preloaded_config_path``)
# so a newly created or edited scenario is picked up by the next Run Sweep.
# Only that scenario's subtree is touched on disk.
# --------------------------------------------------------------------------- #


class CreateScenarioRequest(BaseModel):
    scenario_id: str
    base_scenario_id: Optional[str] = None


class UpdateScenarioRequest(BaseModel):
    yaml: str


class RenameScenarioRequest(BaseModel):
    new_id: str


def _config_path(request: Request) -> Optional[Path]:
    raw = getattr(request.app.state, "preloaded_config_path", None)
    return Path(raw) if raw else None


def _require_config_path(request: Request) -> Path:
    cfg_path = _config_path(request)
    if cfg_path is None:
        raise HTTPException(
            status_code=400,
            detail="No configuration file loaded — scenarios can only be "
            "authored against a config Boulder was started with (a file path, "
            "not an uploaded/pasted config).",
        )
    return cfg_path


def _reload_preloaded_state(request: Request, cfg_path: Path) -> None:
    """Refresh the in-memory preloaded config after an on-disk scenario edit.

    Mirrors the subset of the app's startup load that Run Sweep and the config
    endpoints read (``preloaded_raw`` keeps ``scenarios:``/``sweep:`` for the
    Run Sweep button; ``preloaded_config``/``preloaded_yaml`` back the editor
    panel). Cached simulation results are untouched — editing a scenario
    doesn't invalidate the base config's last solve.
    """
    from ...runner import BoulderRunner

    runner_cls = getattr(request.app.state, "runner_class", None) or BoulderRunner
    raw = runner_cls.load(str(cfg_path))
    request.app.state.preloaded_raw = raw
    with open(cfg_path, "r", encoding="utf-8") as f:
        request.app.state.preloaded_yaml = f.read()
    normalized = runner_cls.normalize(raw)
    request.app.state.preloaded_config = runner_cls.validate(normalized)


@router.get("/{scenario_id}/source")
async def get_scenario_source(scenario_id: str, request: Request) -> Dict[str, Any]:
    """Return one scenario overlay's raw YAML text (for the scoped editor)."""
    cfg_path = _require_config_path(request)
    try:
        from ...scenario_editor import ScenarioEditError, read_scenario

        yaml_text = read_scenario(cfg_path, scenario_id)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"scenario_id": scenario_id, "yaml": yaml_text}


@router.post("")
async def create_scenario(
    body: CreateScenarioRequest, request: Request
) -> Dict[str, Any]:
    """Create a new scenario overlay — blank, or cloned from an existing one."""
    cfg_path = _require_config_path(request)
    try:
        from ...scenario_editor import ScenarioEditError
        from ...scenario_editor import create_scenario as _create

        yaml_text = _create(cfg_path, body.scenario_id, body.base_scenario_id)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reload_preloaded_state(request, cfg_path)
    return {"scenario_id": body.scenario_id, "yaml": yaml_text}


@router.patch("/{scenario_id}")
async def update_scenario(
    scenario_id: str, body: UpdateScenarioRequest, request: Request
) -> Dict[str, Any]:
    """Save edits to a scenario overlay's YAML text."""
    cfg_path = _require_config_path(request)
    try:
        from ...scenario_editor import ScenarioEditError
        from ...scenario_editor import update_scenario as _update

        yaml_text = _update(cfg_path, scenario_id, body.yaml)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reload_preloaded_state(request, cfg_path)
    return {"scenario_id": scenario_id, "yaml": yaml_text}


@router.patch("/{scenario_id}/rename")
async def rename_scenario(
    scenario_id: str, body: RenameScenarioRequest, request: Request
) -> Dict[str, Any]:
    """Rename a scenario's id (its ``scenarios:`` mapping key)."""
    cfg_path = _require_config_path(request)
    try:
        from ...scenario_editor import ScenarioEditError
        from ...scenario_editor import rename_scenario as _rename

        _rename(cfg_path, scenario_id, body.new_id)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reload_preloaded_state(request, cfg_path)
    return {"ok": True, "scenario_id": body.new_id}


@router.post("/clear-cache")
async def clear_scenario_cache(request: Request) -> Dict[str, Any]:
    """Clear every scenario's cached trajectory in the active store.

    Deletes the whole HDF5 store file — the same thing ``--no-cache`` does
    before a sweep — so the next Run Sweep recomputes every scenario from
    scratch. Scenario *definitions* in the config are untouched; only their
    precomputed results disappear until then.
    """
    store = _store_path(request)
    cleared = store is not None and store.is_file()
    if store is not None and cleared:
        store.unlink()
    return {"ok": True, "cleared": cleared}


@router.delete("/{scenario_id}")
async def delete_scenario(scenario_id: str, request: Request) -> Dict[str, Any]:
    """Delete a scenario overlay and purge its cached trajectory, if any.

    Both happen immediately: the definition is removed from the config's
    ``scenarios:`` mapping, and the matching HDF5 group (if the active store
    has one) is deleted right away — not left for the next Run Sweep to
    notice and prune. ``cache_purged`` in the response tells the caller
    whether there was actually a cached result to clear.
    """
    cfg_path = _require_config_path(request)
    try:
        from ...scenario_editor import ScenarioEditError
        from ...scenario_editor import delete_scenario as _delete

        _delete(cfg_path, scenario_id)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    cache_purged = _purge_cached_group(_store_path(request), scenario_id)
    _reload_preloaded_state(request, cfg_path)
    return {"ok": True, "scenario_id": scenario_id, "cache_purged": cache_purged}


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
