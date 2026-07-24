"""Run-sweep API: execute a config's ``sweeps:`` as a background batch job.

A sweep is a heavy, host-specific batch (build + solve every scenario, write the
scenario store), so it is run out-of-process by invoking a ``run_sweep.py`` script
located next to the config. Progress is parsed from the subprocess stdout
(``scenario N/M``); the frontend polls :func:`sweep_status` and refreshes the
Scenario Pane on completion.

Endpoints (prefix ``/api/sweep``):
  GET  ""        -> availability / scenario count / can_run / running
  POST "/run"    -> start the sweep subprocess (409 if one is already running)
  GET  "/status" -> current job status (idle | running | done | error)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...runset import resolve_store_path, run_set_size, sweeps_of

__all__ = ["has_run_set", "resolve_store_path", "router"]

router = APIRouter()


class SweepRunRequest(BaseModel):
    """Body for ``POST /run``. Defaults match the plain "Run Sweep" click."""

    #: Force a full recompute: set BOULDER_NO_CACHE=1 for the subprocess so a
    #: cache-aware host runner discards its collection store and re-solves
    #: every scenario instead of skipping unchanged ones.
    no_cache: bool = False


_SCENARIO_RE = re.compile(r"scenario\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_RUNNER_NAME = "run_sweep.py"


# Run-set sizing lives in boulder.runset (the reference implementation of the
# scenarios:/sweep: union semantics) — the old local mirror is gone.
_run_set_size = run_set_size


def _local_runner_path_for(config_path: Optional[str]) -> Optional[Path]:
    """Return the ``run_sweep.py`` next to *config_path*, if present."""
    if not config_path:
        return None
    local = Path(config_path).resolve().parent / _RUNNER_NAME
    return local if local.is_file() else None


def has_run_set(raw: Dict[str, Any], config_path: Optional[str]) -> bool:
    """Return whether *raw* (the inheritance-resolved config) declares a run-set.

    True when it has an inline ``scenarios:``/``sweep:``/``sweeps:`` block, or a
    ``run_sweep.py`` sits next to the config (a host-defined run-set: the runner
    script decides the cases — e.g. adaptive/bisection sweeps a static ``sweep:``
    block can't express). Pure function of ``(raw, config_path)`` so both the
    request-scoped sweep routes and the app-startup lifespan can share one
    detection rule instead of re-deciding "is this a sweep config?" twice.
    """
    if raw.get("scenarios") or sweeps_of(raw):
        return True
    return _local_runner_path_for(config_path) is not None


def _local_runner_path(request: Request) -> Optional[Path]:
    """Return the ``run_sweep.py`` next to the preloaded config, if present."""
    return _local_runner_path_for(
        getattr(request.app.state, "preloaded_config_path", None)
    )


def _has_run_set(request: Request) -> bool:
    return has_run_set(
        _raw(request), getattr(request.app.state, "preloaded_config_path", None)
    )


def _raw(request: Request) -> Dict[str, Any]:
    return getattr(request.app.state, "preloaded_raw", None) or {}


def _store_path(request: Request) -> Optional[Path]:
    """Return the collection store the run-set writes to (request-scoped wrapper)."""
    return resolve_store_path(
        _raw(request), getattr(request.app.state, "preloaded_config_path", None)
    )


def _runner_command(request: Request) -> Optional[Dict[str, Any]]:
    """Resolve how to run the run-set.

    A ``run_sweep.py`` next to the config, or a host-registered ``sweep_runner``
    command. Returns ``{argv, cwd}`` or None.
    """
    cfg_path = getattr(request.app.state, "preloaded_config_path", None)
    if not cfg_path:
        return None
    cfg = Path(cfg_path).resolve()
    local = cfg.parent / _RUNNER_NAME
    if local.is_file():
        return {
            "argv": [sys.executable, _RUNNER_NAME, cfg.name, "--no-plot"],
            "cwd": str(cfg.parent),
        }
    from ...cantera_converter import get_plugins  # noqa: PLC0415

    runner = getattr(get_plugins(), "sweep_runner", None)
    if runner:
        return {
            "argv": [sys.executable, *runner, str(cfg), "--no-plot"],
            "cwd": str(cfg.parent),
        }
    return None


@router.get("")
async def sweep_info(request: Request) -> Dict[str, Any]:
    """Report whether a run-set (scenarios and/or sweep) can be run."""
    has = _has_run_set(request)
    n = _run_set_size(_raw(request))
    cmd = _runner_command(request)
    job = getattr(request.app.state, "sweep_job", None)
    running = bool(job and job.get("status") == "running")

    if not has:
        reason = "No scenarios or sweep in this config"
    elif cmd is None:
        reason = "No scenario runner available"
    elif n > 0:
        reason = f"Run {n} scenarios"
    else:
        # Host-defined run-set (run_sweep.py decides the cases).
        reason = f"Run the scenario sweep ({_RUNNER_NAME})"

    return {
        "available": has,
        "n_scenarios": n,
        "can_run": has and cmd is not None,
        "reason": reason,
        "running": running,
        # ``--sweep`` GUI mode → frontend defaults the split button to Run Sweep.
        "default": bool(getattr(request.app.state, "sweep_default", False)),
        # ``--run`` → frontend auto-starts the run once on load.
        "autorun": bool(getattr(request.app.state, "autorun", False)),
    }


@router.post("/run")
async def sweep_run(
    request: Request, body: SweepRunRequest = SweepRunRequest()
) -> Dict[str, Any]:
    """Start the run-set subprocess for the preloaded config.

    ``no_cache=true`` forces every scenario to re-solve from scratch.
    """
    cmd = _runner_command(request)
    if not _has_run_set(request) or cmd is None:
        raise HTTPException(
            status_code=400, detail="No runnable run-set for this config"
        )

    job = getattr(request.app.state, "sweep_job", None)
    if job and job.get("status") == "running":
        raise HTTPException(status_code=409, detail="A sweep is already running")

    total = _run_set_size(_raw(request))
    # Point the server at the store the run-set writes so the Scenario Pane shows
    # the results on refresh — even when the config declares no scenario_store.
    store = _store_path(request)
    if store is not None:
        request.app.state.scenario_store_path = str(store)
    state: Dict[str, Any] = {
        "status": "running",
        "current": 0,
        "total": total,
        "message": "starting…",
        "returncode": None,
    }
    request.app.state.sweep_job = state
    # Surface on the server console by default — at least that the run started.
    cache_note = " (no-cache: re-solving everything)" if body.no_cache else ""
    print(
        f"[sweep] starting {total} run(s){cache_note}: {' '.join(cmd['argv'])}",
        flush=True,
    )

    def _worker() -> None:
        try:
            env = os.environ.copy()
            if body.no_cache:
                env["BOULDER_NO_CACHE"] = "1"
            proc = subprocess.Popen(
                cmd["argv"],
                cwd=cmd["cwd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            tail: list[str] = []
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                match = _SCENARIO_RE.search(line)
                if match:
                    state["current"] = int(match.group(1))
                    state["total"] = int(match.group(2))
                    state["message"] = line.strip()
                if line:
                    tail.append(line)
                    del tail[:-30]
                    # Echo the runner's progress to the server console.
                    print(f"[sweep] {line}", flush=True)
            proc.wait()
            state["returncode"] = proc.returncode
            if proc.returncode == 0:
                state["status"] = "done"
                state["message"] = "Sweep complete"
                print(f"[sweep] complete — {state['total']} run(s)", flush=True)
            else:
                state["status"] = "error"
                state["message"] = "\n".join(tail[-8:]) or f"exited {proc.returncode}"
                print(f"[sweep] FAILED (exit {proc.returncode})", flush=True)
        except Exception as exc:  # noqa: BLE001
            state["status"] = "error"
            state["message"] = str(exc)
            print(f"[sweep] FAILED: {exc}", flush=True)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "running", "total": total}


@router.get("/status")
async def sweep_status(request: Request) -> Dict[str, Any]:
    """Return the current sweep job status (for polling)."""
    job = getattr(request.app.state, "sweep_job", None)
    if not job:
        return {"status": "idle"}
    return dict(job)
