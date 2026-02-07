"""Simulation API routes.

Endpoints for starting, streaming, retrieving results, and stopping
Cantera reactor network simulations.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...cantera_converter import DualCanteraConverter
from ...simulation_worker import SimulationWorker, get_simulation_worker
from ..sse import simulation_event_stream

router = APIRouter()

# In-memory mapping of simulation IDs → workers
# For now we support a single concurrent simulation (matching Dash behaviour).
_simulations: Dict[str, SimulationWorker] = {}


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
        _simulations[sim_id] = worker

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
    worker = _simulations.get(sim_id)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

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
async def get_simulation_results(sim_id: str) -> Dict[str, Any]:
    """Return the full simulation results (non-streaming).

    Useful for late-joiners or page refreshes after the simulation
    has completed.
    """
    worker = _simulations.get(sim_id)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

    progress = worker.get_progress()

    if not progress.is_complete and not progress.error_message:
        return {
            "status": "running",
            "is_complete": False,
            "times": progress.times,
            "reactors_series": progress.reactors_series,
        }

    from ..sse import _serialise_reports

    return {
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


@router.delete("/{sim_id}")
async def stop_simulation(sim_id: str) -> Dict[str, Any]:
    """Stop a running simulation."""
    worker = _simulations.get(sim_id)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Simulation {sim_id} not found")

    worker.stop_simulation()
    return {"stopped": True, "simulation_id": sim_id}
