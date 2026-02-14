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
    simulation_time: float = 10.0
    time_step: float = 1.0


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

    # Determine mechanism
    mechanism = body.mechanism
    config = body.config
    if not mechanism:
        phases = config.get("phases", {})
        if isinstance(phases, dict):
            gas = phases.get("gas", {})
            if isinstance(gas, dict):
                mechanism = gas.get("mechanism")
        if not mechanism:
            mechanism = "gri30.yaml"

    try:
        # Build a converter with the resolved mechanism and any plugins
        converter = DualCanteraConverter(mechanism=mechanism)

        # Extract simulation parameters
        settings = config.get("settings", {}) or {}
        simulation_time = body.simulation_time or float(
            settings.get("end_time", settings.get("max_time", 10.0))
        )
        time_step = body.time_step or float(
            settings.get("dt", settings.get("time_step", 1.0))
        )

        # Create a fresh worker for this simulation
        worker = SimulationWorker()
        worker.start_simulation(converter, config, simulation_time, time_step)
        _simulations[sim_id] = (worker, time.time())

        return {"simulation_id": sim_id}

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
        }

    from ..sse import _serialise_reports

    result = {
        "status": "complete" if progress.is_complete else "error",
        "is_complete": progress.is_complete,
        "error_message": progress.error_message,
        "times": progress.times,
        "reactors_series": progress.reactors_series,
        "reactor_reports": _serialise_reports(progress.reactor_reports),
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
async def cleanup_completed_simulations(max_age_seconds: Optional[int] = None) -> Dict[str, Any]:
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
