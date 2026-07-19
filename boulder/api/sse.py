"""Server-Sent Events (SSE) streaming helpers for simulation progress."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, AsyncGenerator, Dict

from ..simulation_worker import SimulationWorker


async def simulation_event_stream(
    worker: SimulationWorker,
    poll_interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    r"""Async generator that yields SSE-formatted simulation progress events.

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
            "stages_done": progress.stages_done,
            "n_stages": progress.n_stages,
            "times": progress.times,
            "reactors_series": progress.reactors_series,
            "reactor_reports": _serialise_reports(progress.reactor_reports),
            "connection_reports": progress.connection_reports.copy(),
            "total_time": progress.total_time,
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
                # Full nodes + connections after post-build hooks and staged
                # solver synthesis — single source of truth for the graph.
                "updated_nodes": progress.updated_nodes,
                "updated_connections": progress.updated_connections,
            }
            yield _sse_event("complete", complete_data)
            return

        # Intermediate progress event
        yield _sse_event("progress", snapshot)
        await asyncio.sleep(poll_interval)


def _sse_event(event_type: str, data: dict) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(sanitize_for_json(data), default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


def sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN/Infinity/-Infinity floats with ``None``.

    ``json.dumps`` emits the bare tokens ``NaN``/``Infinity``/``-Infinity``
    for these values by default (``allow_nan=True``) — valid Python, but
    **not valid JSON**: a strict consumer (JavaScript's ``JSON.parse``,
    which every browser uses) throws a ``SyntaxError`` on them. A single
    NaN anywhere in a large payload (e.g. a derived reactor-report field
    that divides by zero) then silently breaks the whole parse for
    whichever caller wraps it in a bare ``try/catch`` — the simulation
    completes on the backend but the frontend never finds out. Returns a
    new structure; never mutates the input (some of it, like
    ``progress.reactors_series``, is live/actively-appended-to state).
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    return obj


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
