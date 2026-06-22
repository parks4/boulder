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

router = APIRouter()

_SCENARIO_RE = re.compile(r"scenario\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_RUNNER_NAME = "run_sweep.py"


def _sweep_points(sweeps: Dict[str, Any]) -> int:
    """Cartesian-product size of a sweep block's axes (generic; no host import)."""
    if not isinstance(sweeps, dict) or not sweeps:
        return 0
    total = 1
    for axis in sweeps.values():
        if not isinstance(axis, dict):
            continue
        if axis.get("values") is not None:
            n = len(axis["values"])
        elif axis.get("num") is not None:
            n = int(axis["num"])
        elif axis.get("npoints") is not None:
            n = int(axis["npoints"])
        else:
            n = 0
        total *= max(n, 0)
    return total


def _sweep_block(d: Dict[str, Any]) -> Dict[str, Any]:
    return d.get("sweep") or d.get("sweeps") or {}


def _run_set_size(raw: Dict[str, Any]) -> int:
    """Union run-set size (generic; mirrors expand_scenarios without importing it):
    global sweep points ⊎ each `scenario:` entry (its inner sweep, else 1)."""
    scenario = raw.get("scenario") or {}
    total = _sweep_points(_sweep_block(raw))  # global sweep points (0 if none)
    for overlay in scenario.values():
        inner = _sweep_block(overlay or {})
        total += _sweep_points(inner) if inner else 1
    return total


def _has_run_set(request: Request) -> bool:
    raw = getattr(request.app.state, "preloaded_raw", None) or {}
    return bool(raw.get("scenario") or _sweep_block(raw))


def _raw(request: Request) -> Dict[str, Any]:
    return getattr(request.app.state, "preloaded_raw", None) or {}


def _store_path(request: Request) -> Optional[Path]:
    """The collection store the run-set writes — declared
    (``metadata.extra.scenario_store``) or the ``<stem>_scenarios.h5`` default
    (must match the runner's default)."""
    cfg_path = getattr(request.app.state, "preloaded_config_path", None)
    if not cfg_path:
        return None
    cfg = Path(cfg_path).resolve()
    rel = ((_raw(request).get("metadata") or {}).get("extra") or {}).get("scenario_store")
    if rel:
        p = Path(rel)
        return p if p.is_absolute() else cfg.parent / p
    return cfg.parent / f"{cfg.stem}_scenarios.h5"


def _runner_command(request: Request) -> Optional[Dict[str, Any]]:
    """Resolve how to run the run-set: a ``run_sweep.py`` next to the config, or
    a host-registered ``sweep_runner`` command. Returns ``{argv, cwd}`` or None."""
    cfg_path = getattr(request.app.state, "preloaded_config_path", None)
    if not cfg_path:
        return None
    cfg = Path(cfg_path).resolve()
    local = cfg.parent / _RUNNER_NAME
    if local.is_file():
        return {"argv": [sys.executable, _RUNNER_NAME, cfg.name, "--no-plot"], "cwd": str(cfg.parent)}
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
    else:
        reason = f"Run {n} scenarios"

    return {
        "available": has,
        "n_scenarios": n,
        "can_run": has and cmd is not None,
        "reason": reason,
        "running": running,
    }


@router.post("/run")
async def sweep_run(request: Request) -> Dict[str, Any]:
    """Start the run-set subprocess for the preloaded config."""
    cmd = _runner_command(request)
    if not _has_run_set(request) or cmd is None:
        raise HTTPException(status_code=400, detail="No runnable run-set for this config")

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

    def _worker() -> None:
        try:
            proc = subprocess.Popen(
                cmd["argv"],
                cwd=cmd["cwd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=os.environ.copy(),
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
            proc.wait()
            state["returncode"] = proc.returncode
            if proc.returncode == 0:
                state["status"] = "done"
                state["message"] = "Sweep complete"
            else:
                state["status"] = "error"
                state["message"] = "\n".join(tail[-8:]) or f"exited {proc.returncode}"
        except Exception as exc:  # noqa: BLE001
            state["status"] = "error"
            state["message"] = str(exc)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "running", "total": total}


@router.get("/status")
async def sweep_status(request: Request) -> Dict[str, Any]:
    """Return the current sweep job status (for polling)."""
    job = getattr(request.app.state, "sweep_job", None)
    if not job:
        return {"status": "idle"}
    return dict(job)
