"""Server-Sent Events (SSE) streaming helpers for simulation progress."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict

from ..simulation_worker import SimulationWorker


async def simulation_event_stream(
    worker: SimulationWorker,
    poll_interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted simulation progress events.

    Polls the worker every ``poll_interval`` seconds and yields progress
    snapshots until the simulation completes or errors out.

    Parameters
    ----------
    worker
        The simulation worker to poll.
    poll_interval
        Seconds between polls (default 0.5 s).

    Yields
    ------
    str
        SSE-formatted ``event: …\\ndata: …\\n\\n`` strings.
    """
    while True:
        progress = worker.get_progress()

        # Build a JSON-serialisable snapshot (omit non-serialisable objects)
        snapshot: Dict[str, Any] = {
            "is_running": progress.is_running,
            "is_complete": progress.is_complete,
            "error_message": progress.error_message,
            "times": progress.times,
            "reactors_series": progress.reactors_series,
            "reactor_reports": _serialise_reports(progress.reactor_reports),
        }

        if progress.error_message and not progress.is_running:
            yield _sse_event("error", {"message": progress.error_message})
            return

        if progress.is_complete:
            # Final complete event with full results
            complete_data: Dict[str, Any] = {
                **snapshot,
                "code_str": progress.code_str,
                "summary": progress.summary,
                "sankey_links": progress.sankey_links,
                "sankey_nodes": progress.sankey_nodes,
                "elapsed_time": progress.get_calculation_time(),
            }
            yield _sse_event("complete", complete_data)
            return

        # Intermediate progress event
        yield _sse_event("progress", snapshot)
        await asyncio.sleep(poll_interval)


def _sse_event(event_type: str, data: dict) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _serialise_reports(reports: Dict[str, Any]) -> Dict[str, Any]:
    """Make reactor_reports JSON-serialisable by dropping non-serialisable fields."""
    safe: Dict[str, Any] = {}
    for rid, report in reports.items():
        entry: Dict[str, Any] = {}
        for k, v in report.items():
            # numpy arrays → lists
            if hasattr(v, "tolist"):
                entry[k] = v.tolist()
            else:
                entry[k] = v
        safe[rid] = entry
    return safe
