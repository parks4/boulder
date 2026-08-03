"""Run-sweep API: execute a config's ``scenarios:``/``sweep:`` run-set.

Runs in-process, in a background thread, reusing the exact same solve path
``/api/simulations`` uses for a single run (:class:`~boulder.simulation_worker.
SimulationWorker`) — one scenario after another, not a second bespoke
pipeline. Progress is written into ``app.state.sweep_job`` as it goes; the
frontend polls :func:`sweep_status` and refreshes the Scenario Pane on
completion.

The base config comes from the one-time startup snapshot
(``app.state.preloaded_raw``, unchanged for the process lifetime); the
scenario overlays come from the request body — the caller's (``scenarioStore``)
current in-memory overlays map, since scenario authoring no longer writes to
disk (see ``boulder.scenario_editor``). Only the *results* — the HDF5 scenario
store — are written to disk here, same as before.

Endpoints (prefix ``/api/sweep``):
  GET  ""        -> availability / scenario count / can_run / running
  POST "/run"    -> start the sweep (409 if one is already running)
  GET  "/status" -> current job status (idle | running | done | error)
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import h5py
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...cantera_converter import DualCanteraConverter, get_plugins
from ...payload_store import write_payload
from ...runset import resolve_store_path, run_set_size, sweeps_of
from ...sweep_runner import (
    _mechanism_of,
    existing_fingerprints,
    prepare_scenario,
    prune_stale_groups,
    solve_scenario,
)

__all__ = ["has_run_set", "resolve_store_path", "router"]

router = APIRouter()


class SweepRunRequest(BaseModel):
    """Body for ``POST /run``. Defaults match the plain "Run Sweep" click."""

    #: The caller's current in-memory scenario overlays map
    #: (``{scenario_id: overlay_dict}``) — see ``boulder.scenario_editor``.
    scenarios: Dict[str, Any] = Field(default_factory=dict)
    #: Force a full recompute: discard the collection store and re-solve every
    #: scenario instead of skipping ones whose fingerprint is unchanged.
    no_cache: bool = False


def has_run_set(raw: Dict[str, Any], config_path: Optional[str]) -> bool:
    """Return whether *raw* (the inheritance-resolved config) declares a run-set.

    True when it has an inline ``scenarios:``/``sweep:``/``sweeps:`` block.
    Pure function of ``raw`` so both the request-scoped sweep routes and the
    app-startup lifespan can share one detection rule. ``config_path`` is
    accepted for signature compatibility with existing callers; it is not
    otherwise used (Run Sweep runs in-process now — there is no external
    runner script to look for next to the config).
    """
    return bool(raw.get("scenarios") or sweeps_of(raw))


def _has_run_set(request: Request) -> bool:
    return has_run_set(
        _raw(request), getattr(request.app.state, "preloaded_config_path", None)
    )


def _raw(request: Request) -> Dict[str, Any]:
    return getattr(request.app.state, "preloaded_raw", None) or {}


def _merged_raw(request: Request, scenarios: Dict[str, Any]) -> Dict[str, Any]:
    """Return the base config snapshot with *scenarios* (the caller's overlays) merged in.

    The base structure itself is the frozen startup snapshot — not re-read or
    kept in sync with base-network edits, same as every other scenario route
    in this module (see ``boulder.api.routes.scenarios._raw_base_config``).
    """
    base = {k: v for k, v in _raw(request).items() if k != "scenarios"}
    return {**base, "scenarios": scenarios}


def _store_path(request: Request) -> Optional[Path]:
    """Return the collection store the run-set writes to (request-scoped wrapper)."""
    return resolve_store_path(
        _raw(request), getattr(request.app.state, "preloaded_config_path", None)
    )


@router.get("")
async def sweep_info(request: Request) -> Dict[str, Any]:
    """Report whether a run-set (scenarios and/or sweep) can be run.

    Reflects the config's startup snapshot — a scenario created in this
    session but not yet included in a run request isn't counted here (purely
    informational; the actual run in :func:`sweep_run` always uses whatever
    overlays the caller sends).
    """
    has = _has_run_set(request)
    n = run_set_size(_raw(request))
    job = getattr(request.app.state, "sweep_job", None)
    running = bool(job and job.get("status") == "running")

    if not has:
        reason = "No scenarios or sweep in this config"
    elif n > 0:
        reason = f"Run {n} scenarios"
    else:
        reason = "Run the scenario sweep"

    return {
        "available": has,
        "n_scenarios": n,
        "can_run": has,
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
    """Run the run-set in-process, one scenario at a time.

    ``no_cache=true`` forces every scenario to re-solve from scratch.
    """
    raw = _merged_raw(request, body.scenarios)
    total = run_set_size(raw)
    if total == 0:
        raise HTTPException(
            status_code=400, detail="No runnable run-set for this config"
        )

    job = getattr(request.app.state, "sweep_job", None)
    if job and job.get("status") == "running":
        raise HTTPException(status_code=409, detail="A sweep is already running")

    # Point the server at the store the run-set writes so the Scenario Pane shows
    # the results on refresh — even when the config declares no scenario_store.
    store = resolve_store_path(
        raw, getattr(request.app.state, "preloaded_config_path", None)
    )
    if store is None:
        raise HTTPException(
            status_code=400, detail="Could not resolve a scenario store path"
        )
    request.app.state.scenario_store_path = str(store)
    state: Dict[str, Any] = {
        "status": "running",
        "current": 0,
        "total": total,
        "message": "starting…",
        "returncode": None,
        # Keyed by scenario id, e.g. {"cold_feed": {"stage": 1, "stage_total": 3}}.
        # A scenario id's presence here *is* "currently being solved" — a
        # deliberate map rather than a single "current scenario" scalar so a
        # future parallel sweep could hold more than one entry at once without
        # changing this shape.
        "scenario_progress": {},
        # Most recent progress line, verbatim — the frontend shows it under
        # the "Calculating…" spinner so a long solve says *what* it is doing.
        "last_line": None,
    }
    request.app.state.sweep_job = state
    print(f"[sweep] starting {total} run(s)", flush=True)

    def _worker() -> None:
        try:
            from ...runset import expand_scenarios

            store.parent.mkdir(parents=True, exist_ok=True)
            if body.no_cache and store.exists():
                store.unlink()
            cached_fps = {} if body.no_cache else existing_fingerprints(store)

            # Bound once: the host's KPI/artifact hooks are read per scenario
            # below, and the registry is fixed for the process lifetime.
            plugins = get_plugins()

            runs = expand_scenarios(raw)
            run_ids = {sid for sid, _ in runs}
            mechanism = _mechanism_of(raw)
            n_cached = 0
            # The active converter class -- e.g. a host's own subclass with
            # its own mechanism search convention -- lives on `app.state`
            # (set once by the CLI at startup; see `boulder/api/main.py`),
            # the same source `/api/simulations` reads. `get_plugins()` is a
            # *different*, entry-point/env-var-driven registry that a host
            # need not populate the same way, so it can't be relied on here.
            converter_cls = (
                getattr(request.app.state, "converter_class", None)
                or DualCanteraConverter
            )
            # `__new__` avoids constructing a real instance (which would
            # eagerly load a Cantera Solution) just to obtain a method
            # reference -- same trick `_default_resolve_mechanism` uses.
            resolve_mechanism = converter_cls.__new__(converter_cls).resolve_mechanism
            for i, (sid, cfg) in enumerate(runs):
                config, mech_name, fingerprint = prepare_scenario(
                    cfg, resolve_mechanism
                )
                label = str((cfg.get("metadata") or {}).get("scenario_name") or sid)
                state["current"] = i + 1

                if cached_fps.get(sid) == fingerprint:
                    n_cached += 1
                    line = f"scenario {i + 1}/{total} ({sid}): cached, skipped"
                    state["scenario_progress"] = {}
                    state["message"] = line
                    state["last_line"] = line
                    print(f"[sweep] {line}", flush=True)
                    with h5py.File(str(store), "a") as handle:
                        attrs = handle[sid].attrs
                        attrs["label"] = label
                        attrs["order"] = int(i)
                    continue

                line = f"scenario {i + 1}/{total} ({sid})"
                state["scenario_progress"] = {
                    sid: {"stage": None, "stage_total": None, "stage_id": None}
                }
                state["message"] = line
                state["last_line"] = line
                print(f"[sweep] {line}", flush=True)

                # One solve path shared with the CLI runner -- same
                # SimulationWorker a plain "Run Simulation" uses, and one
                # payload builder, so a scenario's stored result does not
                # depend on which button produced it. `progress_cb` is how this
                # route stays able to publish per-stage progress while the
                # solve runs.
                def _publish(progress: Any, _sid: str = sid) -> None:
                    if progress.n_stages:
                        state["scenario_progress"] = {
                            _sid: {
                                "stage": progress.stages_done,
                                "stage_total": progress.n_stages,
                                "stage_id": (
                                    progress.completed_stage_ids[-1]
                                    if progress.completed_stage_ids
                                    else None
                                ),
                            }
                        }

                gui, conv_mechanism, conv = solve_scenario(
                    config,
                    mech_name,
                    converter_cls=converter_cls,
                    progress_cb=_publish,
                )
                # `conv.mechanism` is whatever bare name/spec the converter was
                # constructed with -- resolving it (again) to a real, absolute
                # path is exactly what `resolve_mechanism` is for; `conv`
                # itself never updates `.mechanism` after resolving it
                # internally to load its own `ct.Solution`, so skipping this
                # would hand `write_payload` an unresolved name it can't load.
                stored_mech = resolve_mechanism(conv_mechanism)
                write_payload(store, gui, stored_mech, group=sid, fresh=False)
                # Host KPI attrs (`plugins.scenario_attrs`) -- the numbers the
                # Scenario pane's Sweep Results plot offers as axes. Computed
                # before the h5 handle opens so a raising hook can't leave the
                # store open, and best-effort for the same reason `on_solved`
                # is: a KPI failure must not lose an already-solved scenario.
                extra_attrs: Dict[str, Any] = {}
                if plugins.scenario_attrs is not None:
                    try:
                        extra_attrs = plugins.scenario_attrs(sid, cfg, gui) or {}
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"[sweep] WARNING: scenario_attrs hook failed for "
                            f"'{sid}': {exc}",
                            flush=True,
                        )
                with h5py.File(str(store), "a") as handle:
                    attrs = handle[sid].attrs
                    attrs["label"] = label
                    attrs["order"] = int(i)
                    attrs["fingerprint"] = fingerprint
                    attrs["computed_at"] = float(time.time())
                    for key, value in extra_attrs.items():
                        attrs[key] = value

                # Let the host persist per-scenario artifacts keyed by this
                # fingerprint -- e.g. the single-run result cache, so a later
                # "Export" reuses this solve instead of re-solving. Runs on the
                # in-process path too, not just the out-of-process runner:
                # otherwise a host that registers it silently gets nothing from
                # the GUI's Run Sweep button.
                if plugins.on_scenario_solved is not None:
                    try:
                        from ...simulation_result import make_simulation_result

                        plugins.on_scenario_solved(
                            sid,
                            config,
                            conv,
                            make_simulation_result(conv, config),
                            fingerprint,
                            gui,
                            stored_mech,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"[sweep] WARNING: on_scenario_solved hook failed "
                            f"for '{sid}': {exc}",
                            flush=True,
                        )

            stale = prune_stale_groups(store, run_ids)
            if stale:
                print(
                    f"[sweep] pruned {len(stale)} stale scenario group(s): "
                    f"{', '.join(stale)}",
                    flush=True,
                )

            resolved_mechanism = (
                resolve_mechanism(mechanism) if mechanism else mechanism
            )
            with h5py.File(str(store), "a") as handle:
                cfg_path = getattr(request.app.state, "preloaded_config_path", None)
                handle.attrs["map_config"] = Path(cfg_path).name if cfg_path else ""
                handle.attrs["mechanism"] = resolved_mechanism
                handle.attrs["mechanism_name"] = (
                    Path(mechanism).name if mechanism else ""
                )
                handle.attrs["created_at"] = float(time.time())

            state["scenario_progress"] = {}
            state["last_line"] = None
            state["status"] = "done"
            state["message"] = "Sweep complete"
            print(f"[sweep] complete — {total} run(s)", flush=True)
        except Exception as exc:  # noqa: BLE001
            state["scenario_progress"] = {}
            state["last_line"] = None
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
