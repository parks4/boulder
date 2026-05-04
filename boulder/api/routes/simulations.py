"""Simulation API routes.

Endpoints for starting, streaming, retrieving results, and stopping
Cantera reactor network simulations.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...cantera_converter import DualCanteraConverter
from ...config import TRANSIENT_SOLVER_KINDS, synthesize_default_group
from ...simulation_worker import SimulationWorker
from ..sse import simulation_event_stream

router = APIRouter()

# In-memory mapping of simulation IDs → (worker, creation_timestamp)
# Workers should be removed after completion to prevent memory leaks.
_simulations: Dict[str, tuple[SimulationWorker, float]] = {}


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

        # Extract simulation parameters.  Request-body overrides write into
        # settings.solver so the normaliser / staged solver see them directly.
        settings = config.get("settings", {}) or {}
        settings_simulation_time = float(
            settings.get("end_time", settings.get("max_time", 10.0))
        )
        settings_time_step = float(settings.get("dt", settings.get("time_step", 1.0)))
        simulation_time = (
            body.simulation_time
            if body.simulation_time is not None
            else settings_simulation_time
        )
        time_step = body.time_step if body.time_step is not None else settings_time_step
        _require_positive(time_step, "time_step")

        # When the caller passes explicit time/step overrides, propagate them
        # into settings.solver.grid so the new kind-dispatcher picks them up.
        if body.simulation_time is not None or body.time_step is not None:
            if not isinstance(config.get("settings"), dict):
                config["settings"] = {}
            solver_block = config["settings"].setdefault("solver", {})
            # Only inject grid defaults when no transient kind already specified.
            existing_kind = solver_block.get("kind", "")
            if existing_kind not in TRANSIENT_SOLVER_KINDS:
                solver_block.setdefault("kind", "advance_grid")
            grid = solver_block.setdefault("grid", {})
            grid["stop"] = simulation_time
            grid["dt"] = time_step

        # Create a fresh worker for this simulation
        worker = SimulationWorker()
        worker.start_simulation(converter, config, simulation_time, time_step)
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
        return {
            "status": "running",
            "is_complete": False,
            "times": progress.times,
            "reactors_series": progress.reactors_series,
            "total_time": progress.total_time,
        }

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
    }

    # Optionally clean up completed/errored simulations to free memory
    if cleanup:
        del _simulations[sim_id]

    return result


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
