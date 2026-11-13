"""Simulation API routes.

Endpoints for starting, streaming, retrieving results, and stopping
Cantera reactor network simulations.

A run is a run set of one entry: the route expands the server's live resolved
config (the session's, ``app.state.preloaded_raw``) with the request's scenario
overlays and hands it to :func:`boulder.sweep_runner.run_set`, the pipeline the
sweep route, the CLI and the Python API share.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from ruamel.yaml.error import YAMLError

from ...cantera_converter import get_plugins
from ...runset import base_entry_id, merge_overlays, resolve_store_dir
from ...simulation_worker import RunHandle
from ...sweep_runner import (
    notify_cached,
    prepare_entry,
    run_set,
    selected_entries,
    with_time_overrides,
)
from ..sse import sanitize_for_json, simulation_event_stream

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory mapping of simulation IDs → (run progress, creation_timestamp)
# Entries should be removed after completion to prevent memory leaks.
_simulations: Dict[str, tuple[RunHandle, float]] = {}


def get_completed_simulation_data(sim_id: str) -> Optional[Dict[str, Any]]:
    """Return serialised results for a completed simulation, or None."""
    entry = _simulations.get(sim_id)
    if entry is None:
        return None

    worker, _ = entry
    progress = worker.get_progress()
    if not progress.is_complete or progress.error_message:
        return None

    from ..sse import _serialise_reports

    return {
        "times": progress.times,
        "reactors_series": progress.reactors_series,
        "reactor_reports": _serialise_reports(progress.reactor_reports),
        "connection_reports": progress.connection_reports.copy(),
        "code_str": progress.code_str,
        "summary": progress.summary,
        "sankey_links": progress.sankey_links,
        "sankey_nodes": progress.sankey_nodes,
        "updated_nodes": progress.updated_nodes,
        "updated_connections": progress.updated_connections,
    }


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class StartSimulationRequest(BaseModel):
    """What a run needs from the browser: overlays and an entry id.

    The base config is the server's live one (``app.state.preloaded_raw``), never
    the request's; a stale client still sending ``config`` is refused (422).
    """

    model_config = ConfigDict(extra="forbid")

    simulation_time: Optional[float] = None
    time_step: Optional[float] = None
    #: Run-set entry to solve: the scenario selected in the GUI. ``None`` solves
    #: the base entry.
    scenario_id: Optional[str] = None
    #: The caller's in-memory scenario overlays map, as ``POST /api/sweep/run``
    #: takes it -- ``scenario_id`` is resolved against these. Omitted: the live
    #: config's own ``scenarios:`` section stands (an empty map removes it).
    scenarios: Optional[Dict[str, Any]] = None
    #: Force Run: solve even when the store already holds this entry.
    force: bool = False


def _run_definition(
    request: Request, body: StartSimulationRequest
) -> tuple[Dict[str, Any], str]:
    """Return the resolved config this request runs, and the entry id to solve in it.

    The live config, the request's overlays, then its time overrides written into
    ``settings.solver`` (so the stored definition, the fingerprint and the grid
    all agree). Start and cache check both come through here.
    """
    live = getattr(request.app.state, "preloaded_raw", None)
    if live is None:
        raise HTTPException(
            status_code=409,
            detail="The server holds no config yet: load or edit one first",
        )
    if body.scenarios is not None:
        live = merge_overlays(live, body.scenarios)
    try:
        raw = with_time_overrides(live, body.simulation_time, body.time_step)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return raw, body.scenario_id or base_entry_id(raw)


def _check_entry(raw: Dict[str, Any], entry_id: str) -> None:
    try:
        selected_entries(raw, {entry_id})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("")
def start_simulation(
    body: StartSimulationRequest,
    request: Request,
) -> Dict[str, Any]:
    """Start a new Cantera simulation in a background thread.

    Returns a ``simulation_id`` that can be used to stream progress
    or fetch final results.

    A plain ``def``, like the other routes whose work grows with the network
    (results, cache check): FastAPI runs them in a worker thread, so dumping a
    large config does not stall the event loop that streams progress.
    """
    sim_id = str(uuid.uuid4())
    state = request.app.state
    raw, entry_id = _run_definition(request, body)
    _check_entry(raw, entry_id)

    # Capture the run's source now, from the session as it is at the click: after
    # the solve the file may be gone and a live edit may have replaced the text,
    # and a failure here must stop the run, not lose its entry.
    config_path = getattr(state, "preloaded_config_path", None)
    source = None
    if config_path is not None and resolve_store_dir(raw, config_path):
        from ...scenario_store import build_source  # noqa: PLC0415

        try:
            source = build_source(
                raw,
                config_path,
                leaf_text=getattr(state, "preloaded_yaml", None),
                display_name=getattr(state, "preloaded_filename", None),
            )
        except (OSError, ValueError, YAMLError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Cannot read the run's source: {exc}"
            ) from exc

    handle = RunHandle()

    def _run() -> None:
        try:
            outcomes = run_set(
                raw,
                config_path,
                only={entry_id},
                use_cache=not body.force,
                converter_cls=getattr(state, "converter_class", None),
                runner_cls=getattr(state, "runner_class", None),
                source=source,
                progress_cb=lambda _sid, _cfg, progress: handle.publish(progress),
                stop_event=handle.stop_event,
                keep_payload=True,
            )
            if not outcomes:  # stopped before the entry started
                handle.stopped()
                return
            outcome = outcomes[0]
            # Report completion first: reading the entry back below takes ~10 s
            # on a thousand-reactor network, and the browser already has the
            # payload. GUI actions look the stored entry up themselves.
            store_dir = resolve_store_dir(raw, config_path)
            if store_dir is not None:
                state.preloaded_fingerprint = outcome.fingerprint
            handle.finish(outcome.gui)
            # What the startup check publishes, so `/cached` serves this entry
            # without a server restart.
            if store_dir is not None:
                from ... import scenario_store  # noqa: PLC0415

                state.preloaded_result = scenario_store.load_matching(
                    store_dir,
                    outcome.fingerprint,
                    scenario_store.config_identity(config_path),
                    getattr(state, "converter_class", None),
                )
        except Exception as exc:  # noqa: BLE001 -- reported to the client
            if handle.stop_event.is_set():
                # A cancellation raised out of the solve: an intentional stop.
                logger.info("Simulation stopped: %s", exc)
                handle.stopped()
            else:
                logger.error("Simulation failed: %s", exc, exc_info=True)
                handle.fail(str(exc))

    _simulations[sim_id] = (handle, time.time())
    threading.Thread(target=_run, daemon=True).start()
    return {"simulation_id": sim_id}


@router.get("/{sim_id}/stream")
async def stream_simulation(sim_id: str) -> StreamingResponse:
    """Stream simulation progress as Server-Sent Events (SSE).

    Events emitted:
    - ``progress``: intermediate time-series data
    - ``complete``: final results with code, summary, Sankey
    - ``error``: error message if simulation fails
    """
    entry = _simulations.get(sim_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

    worker, _ = entry

    return StreamingResponse(
        simulation_event_stream(worker),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{sim_id}/results")
def get_simulation_results(sim_id: str, cleanup: bool = False) -> Dict[str, Any]:
    """Return the full simulation results (non-streaming).

    Useful for late-joiners or page refreshes after the simulation
    has completed.

    ``status`` is ``"running"``, ``"stopping"`` (a stop was requested and the
    solve has not unwound yet), or a terminal ``"complete"``, ``"error"`` or
    ``"stopped"`` (ended on request, nothing stored; same word as the SSE
    stream's terminal ``stopped`` event).

    Query parameter ``cleanup=true`` will remove the simulation from
    memory after retrieving results (only once it is terminal).
    """
    entry = _simulations.get(sim_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

    worker, _ = entry
    progress = worker.get_progress()

    # Checked first, as in the SSE stream: a stopped run is terminal and is
    # never reported as errored or complete.
    stopped = progress.is_stopping and not progress.is_running
    if stopped or (not progress.is_complete and not progress.error_message):
        if stopped:
            status = "stopped"
            if cleanup:
                del _simulations[sim_id]
        elif progress.is_stopping:
            status = "stopping"
        else:
            status = "running"
        return sanitize_for_json(
            {
                "status": status,
                "is_complete": False,
                "is_running": progress.is_running,
                "is_stopping": progress.is_stopping,
                "error_message": None,
                "times": progress.times,
                "reactors_series": progress.reactors_series,
                "total_time": progress.total_time,
                "completed_stage_ids": progress.completed_stage_ids,
            }
        )

    from ..sse import _serialise_reports

    result = {
        "status": "complete" if progress.is_complete else "error",
        "is_complete": progress.is_complete,
        "error_message": progress.error_message,
        "times": progress.times,
        "reactors_series": progress.reactors_series,
        "reactor_reports": _serialise_reports(progress.reactor_reports),
        "connection_reports": progress.connection_reports.copy(),
        "code_str": progress.code_str,
        "summary": progress.summary,
        "sankey_links": progress.sankey_links,
        "sankey_nodes": progress.sankey_nodes,
        "elapsed_time": progress.get_calculation_time(),
        "updated_nodes": progress.updated_nodes,
        "updated_connections": progress.updated_connections,
    }

    # Optionally clean up completed/errored simulations to free memory
    if cleanup:
        del _simulations[sim_id]

    return sanitize_for_json(result)


@router.delete("/{sim_id}")
async def stop_simulation(sim_id: str) -> Dict[str, Any]:
    """Request that a running simulation stop.

    Cooperative, not immediate: ``worker.stop_simulation()`` returns right
    away without waiting for the solve thread to actually exit (it used to
    block the request for up to 5 s). The registry entry is deliberately
    *not* removed here -- the open SSE stream (or a late ``/results`` poll)
    still needs to reach it to report the wind-down; it's reaped once the
    thread has actually exited, by :func:`cleanup_completed_simulations`.

    ``/results`` reports ``"stopping"`` until the solve has unwound, then
    ``"stopped"``. How soon that happens depends on the stage's solver kind:
    ``advance_grid`` and ``micro_step`` check the stop between integrator
    steps, while ``advance``, ``advance_to_steady_state`` and ``solve_steady``
    are single blocking Cantera calls, so the stop lands when that call
    returns (the run is still not completed nor stored).
    """
    entry = _simulations.get(sim_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

    worker, _ = entry
    worker.stop_simulation()
    return {"stopping": True, "simulation_id": sim_id}


@router.post("/check-cache")
def check_simulation_cache(
    body: StartSimulationRequest,
    request: Request,
) -> Dict[str, Any]:
    """Check whether the store already holds the entry this request would run.

    Fingerprints the entry exactly as a run would (:func:`prepare_entry` on the
    same resolved config) and returns the matching entry when found.

    Returns ``{"cached": true, "result": {...}, "fingerprint": "...", "meta": {...}}``
    or ``{"cached": false}``.
    """
    from ... import scenario_store

    raw, entry_id = _run_definition(request, body)
    _check_entry(raw, entry_id)
    config_path = getattr(request.app.state, "preloaded_config_path", None)
    store_dir = resolve_store_dir(raw, config_path)
    if store_dir is None:
        logger.info("Result cache disabled (no config path); running a fresh solve.")
        return {"cached": False}

    config, _, fingerprint = prepare_entry(
        raw,
        entry_id,
        runner_cls=getattr(request.app.state, "runner_class", None),
        converter_cls=getattr(request.app.state, "converter_class", None),
    )
    cached = scenario_store.load_matching(
        store_dir,
        fingerprint,
        scenario_store.config_identity(config_path),
        getattr(request.app.state, "converter_class", None),
    )

    if cached is None:
        logger.info(
            "Cache MISS (fingerprint %s): running a fresh solve.", fingerprint[:12]
        )
        return {"cached": False}

    logger.info(
        "Cache HIT (fingerprint %s): retrieving result from cache, skipping solve.",
        fingerprint[:12],
    )
    notify_cached(
        get_plugins().on_scenario_cached,
        store_dir,
        cached["id"],
        config,
        fingerprint,
        identity=scenario_store.config_identity(config_path),
    )
    meta = cached.get("meta", {})
    # gui_payload was written to disk unsanitized (result_cache/payload_store
    # both dump the raw worker output) — a cached NaN/Infinity would otherwise
    # reproduce the exact silent-hang bug this endpoint's live-run sibling
    # (get_simulation_results) already guards against.
    return sanitize_for_json(
        {
            "cached": True,
            "fingerprint": fingerprint,
            "result": cached.get("gui_payload", {}),
            "meta": meta,
        }
    )


@router.get("/cached")
async def get_cached_result(request: Request) -> Dict[str, Any]:
    """Return the cached simulation result for the preloaded configuration.

    Returns ``{"cached": true, "result": {...}, "meta": {...}, "fingerprint": "..."}``
    when a valid cache entry exists for the preloaded config fingerprint, or
    ``{"cached": false}`` otherwise.
    """
    cached = getattr(request.app.state, "preloaded_result", None)
    fingerprint = getattr(request.app.state, "preloaded_fingerprint", None)
    if cached is None:
        return {"cached": False}

    meta = cached.get("meta", {})
    return sanitize_for_json(
        {
            "cached": True,
            "fingerprint": fingerprint,
            "result": cached.get("gui_payload", {}),
            "meta": meta,
        }
    )


@router.get("/cached/artifacts/{artifact_name}")
async def get_cached_artifact(
    artifact_name: str,
    request: Request,
) -> Any:
    """Serve a file from the cached artifacts directory.

    Used by contributor plugins to fetch package-specific
    artifacts they wrote during a previous solve.
    """
    from fastapi.responses import FileResponse

    cached = getattr(request.app.state, "preloaded_result", None)
    if cached is None:
        raise HTTPException(status_code=404, detail="No cached result available")

    artifacts_dir = cached.get("artifacts_dir")
    if artifacts_dir is None:
        raise HTTPException(status_code=404, detail="No artifacts directory in cache")

    from pathlib import Path as _Path

    artifact_path = _Path(artifacts_dir) / artifact_name
    if not artifact_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{artifact_name}' not found in cache",
        )
    # Safety: ensure the resolved path stays inside the artifacts directory
    try:
        artifact_path.resolve().relative_to(_Path(artifacts_dir).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal denied")

    return FileResponse(str(artifact_path))


@router.post("/cleanup")
async def cleanup_completed_simulations(
    max_age_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Clean up completed or errored simulations from memory.

    Parameters
    ----------
    max_age_seconds
        Optional query parameter. If provided, only simulations older than
        this many seconds will be cleaned up. If None, all completed/errored
        simulations are cleaned regardless of age.

    Returns
    -------
    Dict with count of simulations removed.
    """
    to_remove = []
    current_time = time.time()

    for sim_id, (worker, created_at) in _simulations.items():
        progress = worker.get_progress()
        # Only clean up a simulation that has actually reached a terminal
        # state: completed, errored, or stopped (is_stopping and no longer
        # running -- not just "not running", which a worker whose thread
        # hasn't started yet would also match).
        stopped = progress.is_stopping and not progress.is_running
        if progress.is_complete or progress.error_message or stopped:
            # Check age if specified
            if max_age_seconds is None or (current_time - created_at) > max_age_seconds:
                to_remove.append(sim_id)

    for sim_id in to_remove:
        del _simulations[sim_id]

    return {
        "removed": len(to_remove),
        "remaining": len(_simulations),
    }
