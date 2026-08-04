"""Scenario inspector API: list and load precomputed reactor trajectories.

Reads the result store (:mod:`boulder.scenario_store`) — one HDF5 file per
run-set entry, each a Cantera :class:`~cantera.SolutionArray` plus attrs — and
serves each entry as a ``SimulationResults``-shaped payload the frontend renders
through ``setResults`` (the same path a cached solve uses). All entries share one
network topology, so the GUI only swaps result data and never rebuilds the graph.

Store location is derived on demand by :func:`boulder.runset.resolve_store_dir`;
there is no cached path on ``app.state`` to fall out of sync.

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
from pydantic import BaseModel, Field

router = APIRouter()


def _store_dir(request: Request) -> Optional[Path]:
    """Resolve this config's result-store directory.

    Derived on demand rather than cached on ``app.state``: it is pure path
    arithmetic over the startup config snapshot, so there is no state to keep in
    sync (and nothing to go stale if a sweep and a single run disagree about
    where the store lives).
    """
    from ...runset import resolve_store_dir

    return resolve_store_dir(_raw_base_config(request) or {}, _config_path(request))


def _identity(request: Request) -> str:
    """Return the stamp entries must carry to be readable for this config."""
    from ... import scenario_store

    return scenario_store.config_identity(_config_path(request))


def _base_scenarios_snapshot(request: Request) -> Dict[str, Any]:
    """Return the ``scenarios:`` block as loaded at startup — frozen from then on.

    This is the *one* place scenario overlays are ever read from disk: the
    initial seed for the frontend's own overlay state (``scenarioStore``),
    exactly like ``configStore.config`` is seeded once from ``GET
    /configs/preloaded`` and never re-read after. Every scenario authoring
    route past this point is a pure function over whatever overlays map the
    caller sends — nothing here is written back to disk or to ``app.state``.
    """
    raw = _raw_base_config(request) or {}
    overlays = raw.get("scenarios") or {}
    return {k: dict(v or {}) for k, v in overlays.items()}


def _authored_scenario_ids(overlays: Dict[str, Any]) -> List[str]:
    from ...scenario_editor import list_scenario_ids

    return list_scenario_ids(overlays)


@router.get("")
async def list_scenarios(request: Request) -> Dict[str, Any]:
    """List the scenarios in the active store (fast — reads attrs only).

    Also seeds the frontend's scenario-overlay state via ``authored_overlays``
    — see :func:`_base_scenarios_snapshot`.
    """
    from ... import scenario_store

    store_dir = _store_dir(request)
    identity = _identity(request)
    authored_overlays = _base_scenarios_snapshot(request)
    authored_ids = _authored_scenario_ids(authored_overlays)
    entries = scenario_store.list_entries(store_dir, identity)

    # `available` says whether the Scenario pane has anything to show. Every
    # config now has at least one entry (the base run), so store presence alone
    # would light the pane up for every plain single-reactor config -- it is the
    # *authored* scenarios that make the pane meaningful.
    return {
        "available": bool(authored_ids),
        "store": store_dir.name if store_dir else None,
        "mechanism": next(
            (e.get("mechanism_name") for e in entries if e.get("mechanism_name")), None
        ),
        "created_at": max((e.get("computed_at", 0.0) for e in entries), default=None)
        or None,
        # Display units for host-supplied KPI attrs (e.g. scenario_attrs
        # returning ``(value, "%")``). Auto-walked node/connection inputs
        # (``in.<id>.<prop>`` keys) resolve their unit on the frontend instead,
        # via the same property-name lookup the Properties panel uses.
        "units": scenario_store.collect_units(store_dir, identity) or None,
        # Attrs that are bookkeeping, not plottable KPIs. Published rather than
        # duplicated in the frontend: the two lists drifted the moment the store
        # gained an attr (`store_version` was offered as a Sweep Results axis),
        # and a hand-synced copy in another language is the same second source
        # of truth this store exists to remove.
        "non_kpi_keys": sorted(scenario_store.NON_KPI_ATTRS),
        "scenarios": entries,
        "authored_ids": authored_ids,
        "authored_overlays": authored_overlays,
    }


@router.get("/{scenario_id}")
async def get_scenario(scenario_id: str, request: Request) -> Dict[str, Any]:
    """Return one scenario's composite payload (multi-reactor, reports, Sankey)."""
    if h5py is None:
        raise HTTPException(status_code=503, detail="h5py unavailable")
    from ... import scenario_store

    store_dir = _store_dir(request)
    if store_dir is None:
        raise HTTPException(status_code=404, detail="No scenario store available")

    payload = scenario_store.read_entry(store_dir, scenario_id, _identity(request))
    if payload is None:
        # Absent, mid-write, or belonging to another config — all "not computed"
        # from the caller's point of view, none of them a server error.
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario_id!r}")
    return payload


# --------------------------------------------------------------------------- #
# Scenario authoring — create/edit/delete a scenario overlay, in memory only.
#
# Nothing below writes to disk or to `app.state`: every route is a pure
# transform over whatever overlays map the caller (the frontend's
# `scenarioStore`) sends in the request body, mirroring how `/configs/parse`
# already treats the base config (validate/compute, never persist). The only
# way a user gets a scenario onto disk is the Scenario YAML pane's "Download
# full YAML" button (`render_full_yaml` below).
# --------------------------------------------------------------------------- #


class CreateScenarioRequest(BaseModel):
    overlays: Dict[str, Any] = Field(default_factory=dict)
    scenario_id: str
    base_scenario_id: Optional[str] = None
    description: Optional[str] = None


class RenderScenarioRequest(BaseModel):
    overlay: Dict[str, Any] = Field(default_factory=dict)


class PreviewScenarioRequest(BaseModel):
    overlay: Dict[str, Any] = Field(default_factory=dict)


class UpdateScenarioRequest(BaseModel):
    overlays: Dict[str, Any] = Field(default_factory=dict)
    yaml: str


class UpdateScenarioEntityRequest(BaseModel):
    overlays: Dict[str, Any] = Field(default_factory=dict)
    properties: Dict[str, Any]


class RenameScenarioRequest(BaseModel):
    overlays: Dict[str, Any] = Field(default_factory=dict)
    new_id: str


class DeleteScenarioRequest(BaseModel):
    overlays: Dict[str, Any] = Field(default_factory=dict)


def _config_path(request: Request) -> Optional[Path]:
    raw = getattr(request.app.state, "preloaded_config_path", None)
    return Path(raw) if raw else None


def _raw_base_config(request: Request) -> Optional[Dict[str, Any]]:
    """Return the inheritance-resolved base config dict (keeps `scenarios:`/`sweep:`).

    Prefers the in-memory startup snapshot (`app.state.preloaded_raw`); falls
    back to a fresh disk load so this also works against a config path set
    directly (e.g. in tests) without a preload having happened yet. This is a
    read-only structural reference for `_entity_location`/preview/render — not
    kept in sync with scenario edits, which live entirely in the caller's
    overlays map.
    """
    raw = getattr(request.app.state, "preloaded_raw", None)
    if raw:
        return raw
    cfg_path = _config_path(request)
    if cfg_path is None or not cfg_path.is_file():
        return None
    from ...runner import BoulderRunner

    runner_cls = getattr(request.app.state, "runner_class", None) or BoulderRunner
    return runner_cls.load(str(cfg_path))


def _require_base_raw(request: Request) -> Dict[str, Any]:
    raw = _raw_base_config(request)
    if not raw:
        raise HTTPException(status_code=404, detail="No configuration loaded")
    return raw


@router.post("/{scenario_id}/source")
async def get_scenario_source(
    scenario_id: str, body: RenderScenarioRequest
) -> Dict[str, Any]:
    """Render one scenario overlay's YAML text (for the scoped editor).

    Stateless: *body.overlay* is whatever the caller currently has for this
    scenario id (its own `scenarioStore.overlays[scenario_id]`) — there is no
    server-side copy to fetch from.
    """
    from ...scenario_editor import _overlay_yaml_text

    return {"scenario_id": scenario_id, "yaml": _overlay_yaml_text(body.overlay)}


@router.post("/{scenario_id}/preview")
async def get_scenario_preview(
    scenario_id: str, body: PreviewScenarioRequest, request: Request
) -> Dict[str, Any]:
    """Return the effective node/connection properties for one authored scenario.

    Lets the Inputs pane show a scenario's parameter overrides (e.g. a reactor's
    ``length``) the moment it's selected — even before Run Sweep has produced a
    trajectory for it. Mirrors :func:`boulder.runset.expand_scenarios`'s base ⊕
    overlay merge for a single scenario id, using *body.overlay* (the caller's
    current in-memory overlay) as-is: an inner ``sweep:`` block's axis values
    are not expanded here (this is a static preview, not a resolved run-set
    point), and BASELINE is previewed by sending an empty overlay.
    """
    raw = _require_base_raw(request)

    from ...runner import BoulderRunner
    from ...runset import deep_merge

    base_clean = {
        k: v for k, v in raw.items() if k not in ("scenarios", "sweep", "sweeps")
    }
    overlay = dict(body.overlay)
    overlay.pop("sweep", None)
    overlay.pop("sweeps", None)
    merged = deep_merge(base_clean, overlay)

    runner_cls = getattr(request.app.state, "runner_class", None) or BoulderRunner
    try:
        normalized = runner_cls.normalize(merged)
    except Exception as exc:  # noqa: BLE001 — surfaced as a 422 to the preview caller
        raise HTTPException(
            status_code=422,
            detail=f"Could not preview scenario {scenario_id!r}: {exc}",
        ) from exc

    return {
        "scenario_id": scenario_id,
        "nodes": normalized.get("nodes", []),
        "connections": normalized.get("connections", []),
    }


@router.post("/{scenario_id}/render-full")
async def render_full_yaml(
    scenario_id: str, body: RenderScenarioRequest, request: Request
) -> Dict[str, Any]:
    """Return the base config deep-merged with one scenario's overlay, as full YAML text.

    Backs the Scenario YAML pane's "Download full YAML" button — the one
    sanctioned way to get an edited scenario onto disk now that nothing here
    auto-persists.
    """
    raw = _require_base_raw(request)
    from ...scenario_editor import render_full_yaml as _render

    return {"scenario_id": scenario_id, "yaml": _render(raw, body.overlay)}


@router.post("")
async def create_scenario(body: CreateScenarioRequest) -> Dict[str, Any]:
    """Create a new scenario overlay — blank, or cloned from an existing one."""
    from ...scenario_editor import ScenarioEditError
    from ...scenario_editor import create_scenario as _create

    try:
        new_overlays, yaml_text = _create(
            body.overlays, body.scenario_id, body.base_scenario_id, body.description
        )
    except ScenarioEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "scenario_id": body.scenario_id,
        "yaml": yaml_text,
        "overlays": new_overlays,
    }


@router.patch("/{scenario_id}")
async def update_scenario(
    scenario_id: str, body: UpdateScenarioRequest
) -> Dict[str, Any]:
    """Apply edits to a scenario overlay's YAML text."""
    from ...scenario_editor import ScenarioEditError
    from ...scenario_editor import update_scenario as _update

    try:
        new_overlays, yaml_text = _update(body.overlays, scenario_id, body.yaml)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"scenario_id": scenario_id, "yaml": yaml_text, "overlays": new_overlays}


@router.patch("/{scenario_id}/entities/{entity_id}")
async def update_scenario_entity(
    scenario_id: str,
    entity_id: str,
    body: UpdateScenarioEntityRequest,
    request: Request,
) -> Dict[str, Any]:
    """Merge edited properties into one node/connection's overlay entry.

    Backs the Properties panel's "Save" while a scenario is active — edits
    land in that scenario's overlay instead of the base network. Node vs.
    connection, and which stage list it belongs to, is resolved from the
    base config itself (see ``scenario_editor._entity_location``) — the
    caller only needs the id.
    """
    raw = _require_base_raw(request)
    from ...scenario_editor import ScenarioEditError
    from ...scenario_editor import update_scenario_entity as _update_entity

    try:
        new_overlays, yaml_text = _update_entity(
            body.overlays, raw, scenario_id, entity_id, body.properties
        )
    except ScenarioEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "scenario_id": scenario_id,
        "id": entity_id,
        "yaml": yaml_text,
        "overlays": new_overlays,
    }


@router.patch("/{scenario_id}/rename")
async def rename_scenario(
    scenario_id: str, body: RenameScenarioRequest
) -> Dict[str, Any]:
    """Rename a scenario's id (its overlays-map key)."""
    from ...scenario_editor import ScenarioEditError
    from ...scenario_editor import rename_scenario as _rename

    try:
        new_overlays = _rename(body.overlays, scenario_id, body.new_id)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "scenario_id": body.new_id, "overlays": new_overlays}


@router.post("/clear-cache")
async def clear_scenario_cache(request: Request) -> Dict[str, Any]:
    """Clear every entry's cached result for the active config.

    Removes the whole store directory — every entry's file *and* the host
    artifacts beside them, which a per-file delete would otherwise orphan. This
    only ever touched cached *results*, never a scenario definition, so it is
    unaffected by scenario authoring being in-memory.
    """
    from ... import scenario_store

    return {"ok": True, "cleared": scenario_store.clear(_store_dir(request))}


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: str, body: DeleteScenarioRequest, request: Request
) -> Dict[str, Any]:
    """Delete a scenario overlay and purge its cached trajectory, if any.

    The overlay is removed from the returned overlays map immediately; the
    matching store entry (and its artifacts) is deleted right away too — not
    left for the next Run Sweep to notice and prune. ``cache_purged`` in the
    response tells the caller whether there was actually a cached result to
    clear.
    """
    from ... import scenario_store
    from ...scenario_editor import ScenarioEditError
    from ...scenario_editor import delete_scenario as _delete

    try:
        new_overlays = _delete(body.overlays, scenario_id)
    except ScenarioEditError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store_dir = _store_dir(request)
    cache_purged = (
        scenario_store.delete_entry(store_dir, scenario_id)
        if store_dir is not None
        else False
    )
    return {
        "ok": True,
        "scenario_id": scenario_id,
        "cache_purged": cache_purged,
        "overlays": new_overlays,
    }


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
    from ... import scenario_store

    store_dir = _store_dir(request)
    if store_dir is None:
        raise HTTPException(status_code=404, detail="No scenario store available")
    known = {
        e["id"] for e in scenario_store.list_entries(store_dir, _identity(request))
    }
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
