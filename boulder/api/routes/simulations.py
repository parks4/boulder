"""Simulation API routes.

Endpoints for starting, streaming, retrieving results, and stopping
Cantera reactor network simulations.
"""

from __future__ import annotations

import copy
import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...cantera_converter import DualCanteraConverter
from ...config import TRANSIENT_SOLVER_KINDS, synthesize_default_group
from ...simulation_worker import SimulationWorker
from ..sse import sanitize_for_json, simulation_event_stream

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory mapping of simulation IDs → (worker, creation_timestamp)
# Workers should be removed after completion to prevent memory leaks.
_simulations: Dict[str, tuple[SimulationWorker, float]] = {}


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
    config: Dict[str, Any]
    mechanism: Optional[str] = None
    simulation_time: Optional[float] = None
    time_step: Optional[float] = None


def _require_positive(value: float, name: str) -> None:
    """Validate that a numeric simulation parameter is strictly positive."""
    if value <= 0:
        raise HTTPException(status_code=422, detail=f"{name} must be > 0")


def _first_finite(*values: Any, default: float) -> float:
    """Return the first non-``None`` value in *values*, else *default*.

    Used to resolve a run-duration/step field from an ordered list of
    fallback sources (body override, legacy config keys, the current
    grid/advance_time schema) without a nested ``dict.get(key, dict.get(...))``
    chain, which mypy cannot always narrow to a definite non-``None`` type by
    the time it reaches the final ``float(...)`` call.
    """
    for v in values:
        if v is not None:
            return float(v)
    return default


def _resolve_run_grid(
    config: Dict[str, Any],
    body_simulation_time: Optional[float],
    body_time_step: Optional[float],
) -> tuple[float, float]:
    """Resolve the run time/step and inject explicit overrides into the config.

    Request-body overrides write into ``settings.solver.grid`` (in place) so
    the normaliser / staged solver see them directly. This is the single
    normalization both the run path and the cache check use: the cache
    fingerprint is computed from the pre-build config, so a cache lookup must
    transform the submitted config exactly like a run would.
    """
    settings = config.get("settings", {}) or {}
    solver = settings.get("solver") or {}
    grid = solver.get("grid")
    grid = grid if isinstance(grid, dict) else {}
    # The current schema (settings.solver.grid.{start,stop,dt} for advance_grid/
    # micro_step, or settings.solver.advance_time for the flat "advance" kind)
    # is checked before the legacy top-level end_time/max_time/dt/time_step
    # keys, so total_time/progress reporting reflects the real grid even
    # though nothing here writes those legacy keys.
    settings_simulation_time = _first_finite(
        settings.get("end_time"),
        settings.get("max_time"),
        grid.get("stop"),
        solver.get("advance_time"),
        default=10.0,
    )
    settings_time_step = _first_finite(
        settings.get("dt"), settings.get("time_step"), grid.get("dt"), default=1.0
    )
    simulation_time = (
        body_simulation_time
        if body_simulation_time is not None
        else settings_simulation_time
    )
    time_step = body_time_step if body_time_step is not None else settings_time_step
    _require_positive(time_step, "time_step")

    # When the caller passes explicit time/step overrides, propagate them
    # into settings.solver.grid so the new kind-dispatcher picks them up.
    if body_simulation_time is not None or body_time_step is not None:
        if not isinstance(config.get("settings"), dict):
            config["settings"] = {}
        solver_block = config["settings"].setdefault("solver", {})
        # Only inject grid defaults when no transient kind already specified.
        existing_kind = solver_block.get("kind", "")
        if existing_kind not in TRANSIENT_SOLVER_KINDS:
            solver_block.setdefault("kind", "advance_grid")
        # Respect an already-declared grid (e.g. an explicit list of save
        # times, or a {start,stop,dt} dict) — it is authoritative. Only
        # synthesize a {stop,dt} grid from the time/step overrides when none
        # exists yet (avoids indexing a list grid as a dict).
        existing_grid = solver_block.get("grid")
        if isinstance(existing_grid, dict):
            existing_grid["stop"] = simulation_time
            existing_grid["dt"] = time_step
        elif existing_grid is None:
            solver_block["grid"] = {"stop": simulation_time, "dt": time_step}
        # else: explicit list grid — leave it untouched.
    return simulation_time, time_step


def normalize_config_for_fingerprint(
    config: Dict[str, Any],
    simulation_time: Optional[float] = None,
    time_step: Optional[float] = None,
) -> Dict[str, Any]:
    """Copy of ``config`` transformed exactly as a run fingerprints it.

    The worker fingerprints the pre-build config AFTER default-group
    synthesis and after any explicit time/step overrides were injected into
    ``settings.solver.grid`` — every cache lookup must apply the same
    transforms or identical configs hash differently. The input is left
    untouched.
    """
    normalized = copy.deepcopy(config)
    synthesize_default_group(normalized)
    _resolve_run_grid(normalized, simulation_time, time_step)
    return normalized


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("")
async def start_simulation(
    body: StartSimulationRequest,
    request: Request,
) -> Dict[str, Any]:
    """Start a new Cantera simulation in a background thread.

    Returns a ``simulation_id`` that can be used to stream progress
    or fetch final results.
    """
    sim_id = str(uuid.uuid4())

    # The frontend always sends an already-normalized config (expanded composite
    # satellites, flat groups/nodes/connections form).  We must NOT call
    # normalize_config here — expand_composite_kinds is not idempotent and
    # would raise a collision error for any composite reactor whose satellite
    # nodes are already present in the node list.
    #
    # synthesize_default_group IS idempotent: it only adds a "default" group
    # when none exists, which build_network requires.
    config: Dict[str, Any] = dict(body.config)
    synthesize_default_group(config)

    # Determine mechanism
    mechanism = body.mechanism
    if not mechanism:
        phases = config.get("phases", {})
        if isinstance(phases, dict):
            gas = phases.get("gas", {})
            if isinstance(gas, dict):
                mechanism = gas.get("mechanism")
        if not mechanism:
            mechanism = "gri30.yaml"

    try:
        # Build a converter with the resolved mechanism.
        # Use the converter class registered at startup (may be substituted by subclass)
        # so subclass overrides (like resolve_mechanism) are respected.
        converter_cls = getattr(
            request.app.state, "converter_class", DualCanteraConverter
        )
        converter = converter_cls(mechanism=mechanism)
        # Propagate the original YAML path so the generated downloadable script
        # references the correct file instead of the "config.yaml" placeholder.
        config_path = getattr(request.app.state, "preloaded_config_path", None)
        if config_path is not None:
            converter._download_config_path = config_path

        # Extract simulation parameters and inject explicit overrides into
        # settings.solver (shared with the cache check, which must fingerprint
        # the exact config a run would save).
        simulation_time, time_step = _resolve_run_grid(
            config, body.simulation_time, body.time_step
        )

        # Create a fresh worker for this simulation.
        # Pass app.state so the worker can update preloaded_result after the
        # solve completes without requiring a server restart.
        worker = SimulationWorker()
        worker.start_simulation(
            converter,
            config,
            simulation_time,
            time_step,
            app_state=request.app.state,
        )
        _simulations[sim_id] = (worker, time.time())

        return {"simulation_id": sim_id}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
async def get_simulation_results(sim_id: str, cleanup: bool = False) -> Dict[str, Any]:
    """Return the full simulation results (non-streaming).

    Useful for late-joiners or page refreshes after the simulation
    has completed.

    Query parameter ``cleanup=true`` will remove the simulation from
    memory after retrieving results (only if complete or errored).
    """
    entry = _simulations.get(sim_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

    worker, _ = entry
    progress = worker.get_progress()

    if not progress.is_complete and not progress.error_message:
        return sanitize_for_json(
            {
                "status": "running",
                "is_complete": False,
                "times": progress.times,
                "reactors_series": progress.reactors_series,
                "total_time": progress.total_time,
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
    """Stop a running simulation and remove it from memory."""
    entry = _simulations.get(sim_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

    worker, _ = entry
    worker.stop_simulation()
    # Remove the worker from the dictionary to free memory
    del _simulations[sim_id]
    return {"stopped": True, "simulation_id": sim_id}


@router.post("/check-cache")
async def check_simulation_cache(
    body: StartSimulationRequest,
    request: Request,
) -> Dict[str, Any]:
    """Check whether a cached result exists for the submitted config.

    Computes the fingerprint from ``body.config`` (exactly as the simulation
    worker would) and returns the matching entry when found.

    Returns ``{"cached": true, "result": {...}, "fingerprint": "...", "meta": {...}}``
    or ``{"cached": false}``.
    """
    from ...result_cache import (
        cache_dir_for,
        lookup_cached_result,
        resolve_mechanism_for_fingerprint,
    )

    # Normalize exactly like a run would (transient re-runs included).
    config = normalize_config_for_fingerprint(
        body.config, body.simulation_time, body.time_step
    )
    converter_cls = getattr(request.app.state, "converter_class", None)
    mechanism = resolve_mechanism_for_fingerprint(
        config,
        converter_class=converter_cls,
        body_mechanism=body.mechanism,
    )

    config_path = getattr(request.app.state, "preloaded_config_path", None)
    cache_root = cache_dir_for(config_path)
    if cache_root is None:
        logger.info("Result cache disabled (no config path); running a fresh solve.")
        return {"cached": False}

    preloaded = getattr(request.app.state, "preloaded_result", None)
    fingerprint, cached = lookup_cached_result(
        cache_root,
        config,
        mechanism=mechanism,
        preloaded_result=preloaded,
    )
    # cache_root is set (guarded above), so the fingerprint is always computed.
    assert fingerprint is not None

    if cached is None:
        logger.info(
            "Cache MISS (fingerprint %s): running a fresh solve.", fingerprint[:12]
        )
        return {"cached": False}

    logger.info(
        "Cache HIT (fingerprint %s): retrieving result from cache, skipping solve.",
        fingerprint[:12],
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
            "config_snapshot": cached.get("config_snapshot", {}),
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
            "config_snapshot": cached.get("config_snapshot", {}),
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
        # Only clean up if completed or errored
        if progress.is_complete or progress.error_message:
            # Check age if specified
            if max_age_seconds is None or (current_time - created_at) > max_age_seconds:
                to_remove.append(sim_id)

    for sim_id in to_remove:
        del _simulations[sim_id]

    return {
        "removed": len(to_remove),
        "remaining": len(_simulations),
    }
