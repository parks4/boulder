"""Generic scenario/sweep runner → composite collection store (for the GUI Run Sweep).

Invoked out-of-process by the ``/api/sweep`` routes for any config that declares
``scenarios:`` and/or ``scenarios_sweep:``. It:

1. loads the raw config (``from:`` inheritance resolved),
2. pulls the union run-set from :func:`boulder.runset.iter_run_set` -- grid
   points and overlays up front, a ``for:``/``while:`` chain one point at a
   time, each built from the previous step's converged state,
3. solves each run through the Boulder converter, and
4. writes each result into the run-set store
   (``metadata.extra.cache_store``, default ``.boulder-cache/<stem>/``), one
   ``<scenario_id>.h5`` file per run,

printing ``scenario N/M`` per run so the sweep API can show progress. The
Scenario Pane then lists every run and opens each instantly.

Caching is incremental by default: each group carries the Boulder cache
fingerprint of its config (:func:`scenario_fingerprint`), and runs whose
fingerprint is unchanged are skipped. ``BOULDER_NO_CACHE`` forces a full
recompute, recreating the store from scratch. Groups whose scenario id left
the run-set are pruned.

Usage: ``python -m boulder.sweep_runner <config.yaml> [--no-plot]``

Host packages with extra needs keep their own entry point (registered via
``plugins.sweep_runner``) as a thin wrapper around :func:`run`, passing hooks:
``setup`` for process-level preparation (e.g. putting a private mechanism
directory on Cantera's search path), ``resolve_mechanism`` to turn bare
mechanism names into absolute paths (so the GUI server can read the store
without the host's search-path setup), and ``scenario_attrs`` to attach extra
scalar KPI attributes to each scenario group (what the Sweep Results plot
reads).
"""

from __future__ import annotations

import argparse
import copy
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
)

from . import scenario_store
from .cantera_converter import DualCanteraConverter, get_plugins, select_converter_class
from .config import normalize_config, synthesize_default_group
from .result_cache import get_cache_contributor_registry, run_contributors
from .runset import (
    RUN_SET_KEYS,
    RunSetCursor,
    base_entry_id,
    expand_scenarios,
    iter_run_set,
    node_property_attrs,
    resolve_store_dir,
    run_set_size,
    sequential_of,
    store_artifacts_dir,
    sweep_point_of,
)

logger = logging.getLogger(__name__)

#: Mechanism hashed (and solved) when a scenario names none.
DEFAULT_MECHANISM = "gri30.yaml"


def _mechanism_of(raw: Dict[str, Any]) -> str:
    gas = (raw.get("phases") or {}).get("gas") or {}
    return str(gas.get("mechanism") or "")


def converter_mechanism_resolver(
    converter_cls: Optional[Type[DualCanteraConverter]],
) -> Callable[[str], str]:
    """Bound ``resolve_mechanism`` of ``converter_cls`` (base class if ``None``).

    One resolver for every fingerprint site -- the solve (:func:`solve_scenario`),
    the cache key, the store, the cache-check route and the startup preload -- so
    a host's converter subclass (its own mechanism search convention) resolves
    consistently everywhere. The base :class:`DualCanteraConverter` passes the
    name through unchanged.

    Uses ``__new__`` rather than a constructor call: ``__init__`` eagerly loads a
    real ``ct.Solution`` for the (possibly default) mechanism, which would be
    wasteful -- or fail for a host with no sensible default -- just to obtain a
    method reference. This assumes ``resolve_mechanism`` overrides don't depend
    on ``__init__``-set instance state (true for the base class; a host override
    must preserve this).
    """
    converter_cls = converter_cls or DualCanteraConverter
    return converter_cls.__new__(converter_cls).resolve_mechanism


def scenario_fingerprint(
    raw_cfg: Dict[str, Any],
    *,
    extra: Optional[Dict[str, Any]] = None,
    resolve_mechanism: Optional[Callable[[str], str]] = None,
    normalized: bool = False,
    mechanism: Optional[str] = None,
) -> str:
    """Boulder cache fingerprint for one scenario.

    THE fingerprint every scenario store uses -- this runner, the single-run
    worker, the cache-check route and any host batch writer all call this; do
    not re-implement the cache key elsewhere. ``extra`` mixes caller-specific
    inputs into the hash (e.g. a save grid that lives outside the solved
    network config). ``resolve_mechanism`` maps a bare mechanism name to the
    identity actually hashed -- defaults to the resolver derived from
    ``plugins.converter_class`` (see :func:`converter_mechanism_resolver`) so
    fingerprints match the store contents without the caller needing to pass
    its own resolver explicitly. Resolver errors propagate.

    ``raw_cfg`` is a merged (``from:``-resolved) scenario by default. With
    ``normalized=True`` it is already in the internal form (what the GUI holds
    and sends back): ``normalize_config`` is skipped because it is not
    idempotent, and only the idempotent default-group synthesis is applied.
    ``mechanism`` overrides ``phases.gas.mechanism``; with neither, the
    converter's own default (``gri30.yaml``) is hashed.
    """
    from .result_cache import compute_fingerprint  # noqa: PLC0415

    plugins = get_plugins()
    config = copy.deepcopy(raw_cfg)
    if normalized:
        synthesize_default_group(config)
    else:
        config = normalize_config(config, plugins=plugins)
    name = mechanism or _mechanism_of(raw_cfg) or DEFAULT_MECHANISM
    resolve_mechanism = resolve_mechanism or converter_mechanism_resolver(
        plugins.converter_class
    )
    return compute_fingerprint(config, mechanism=resolve_mechanism(name), extra=extra)


def prepare_scenario(
    raw_cfg: Dict[str, Any],
    resolve_mechanism: Optional[Callable[[str], str]],
    runner_cls: Optional[Any] = None,
) -> Tuple[Dict[str, Any], str, str]:
    """Normalize a merged scenario config → ``(config, mechanism, fingerprint)``.

    The fingerprint (Boulder's cache key) lets the run skip scenarios that are
    already cached unchanged — computed without building/solving the network.
    The config goes through *runner_cls*'s ``normalize`` then ``validate`` (a
    host's own preparation; default :class:`~boulder.runner.BoulderRunner`), so
    an entry hashes the same whichever entry point solves it.
    Public: shared with any out-of-process caller that needs to solve exactly
    one scenario the same way this runner does (e.g. an "Export" GUI action
    solving a cache-miss scenario on demand).
    """
    from .runner import BoulderRunner  # noqa: PLC0415 — cycle

    runner_cls = runner_cls or BoulderRunner
    config = runner_cls.validate(runner_cls.normalize(copy.deepcopy(raw_cfg)))
    mechanism = _mechanism_of(raw_cfg)
    fingerprint = scenario_fingerprint(
        config,
        normalized=True,
        mechanism=mechanism,
        resolve_mechanism=resolve_mechanism,
    )
    return config, mechanism, fingerprint


def solver_window(config: Dict[str, Any]) -> Tuple[float, float]:
    """Return ``(simulation_time, time_step)`` for one prepared config.

    THE time-grid rule, read by every entry point from the prepared config only.
    The window is what the solve integrates: ``settings.solver.grid.stop`` (the
    last time of a list grid) or ``advance_time``; ``settings.end_time`` is only
    the fallback when the solver names no end. When both are given and differ the
    solver wins and a warning says so. The step is ``grid.dt``, else
    ``settings.dt``, else a tenth of the window. A config with no time at all
    (steady stages only) gets ``(0.0, 0.0)`` -- the time arguments are unused once
    the staged solve is done. There is no hidden default duration: a *transient*
    stage with no grid is an error when it is built
    (:meth:`~boulder.cantera_converter.DualCanteraConverter.build_network`).
    """
    settings = config.get("settings") or {}
    solver = settings.get("solver") or {}
    grid = solver.get("grid")
    if isinstance(grid, dict):
        stop, grid_dt = grid.get("stop"), grid.get("dt")
    else:
        stop, grid_dt = (grid[-1] if grid else None), None
    solver_end = float(stop or solver.get("advance_time") or 0.0)
    end_time = float(settings.get("end_time") or 0.0)
    if solver_end and end_time and solver_end != end_time:
        logger.warning(
            "settings.end_time (%g) and the solver's end (%g) differ; "
            "the solver's is what is integrated.",
            end_time,
            solver_end,
        )
    sim_t = solver_end or end_time
    dt = float(grid_dt or settings.get("dt") or 0.0) or sim_t / 10.0
    return sim_t, dt


def with_time_overrides(
    raw: Dict[str, Any],
    simulation_time: Optional[float],
    time_step: Optional[float],
) -> Dict[str, Any]:
    """Return a copy of the resolved config *raw* with the GUI's time overrides in.

    The GUI's run-time/step fields are written into ``settings.solver`` before
    the run-set is expanded, so the stored definition, the fingerprint, sweeps
    and the grid all see them. The config is the session's, never a file:
    nothing is written to disk. With no override, *raw* itself is returned.
    """
    if simulation_time is None and time_step is None:
        return raw
    for name, value in (("simulation_time", simulation_time), ("time_step", time_step)):
        if value is not None and value <= 0:
            raise ValueError(f"{name} must be > 0")
    from .config import TRANSIENT_SOLVER_KINDS  # noqa: PLC0415

    raw = copy.deepcopy(raw)
    if not isinstance(raw.get("settings"), dict):
        raw["settings"] = {}
    solver = raw["settings"].setdefault("solver", {})
    # Only name a kind when no transient one is declared.
    if solver.get("kind", "") not in TRANSIENT_SOLVER_KINDS:
        solver.setdefault("kind", "advance_grid")
    grid = solver.get("grid")
    if solver["kind"] == "advance":
        # `advance` integrates to `advance_time` and has no step or grid.
        if simulation_time is not None:
            solver["advance_time"] = simulation_time
    elif isinstance(grid, dict):
        if simulation_time is not None:
            grid["stop"] = simulation_time
        if time_step is not None:
            grid["dt"] = time_step
    elif grid is None:
        stop, dt = solver_window(raw)
        stop = simulation_time if simulation_time is not None else stop
        dt = time_step if time_step is not None else dt
        if not stop or not dt:
            raise ValueError("simulation_time and time_step are both needed here")
        solver["grid"] = {"stop": stop, "dt": dt}
    # else: an explicit list of save times is authoritative -- left untouched.
    # The nominal window follows, so it never disagrees with the grid.
    if simulation_time is not None and "end_time" in raw["settings"]:
        raw["settings"]["end_time"] = simulation_time
    if time_step is not None and "dt" in raw["settings"]:
        raw["settings"]["dt"] = time_step
    return raw


def solve_scenario(
    config: Dict[str, Any],
    mechanism: str,
    *,
    converter_cls: Optional[Type[Any]] = None,
    progress_cb: Optional[Callable[[Any], None]] = None,
    poll_interval: float = 0.05,
    stop_event: Optional[threading.Event] = None,
    config_path: "Optional[str | Path]" = None,
) -> Tuple[Dict[str, Any], str, DualCanteraConverter]:
    """Solve one normalized scenario config → (gui_payload, mechanism, converter).

    **The single solve path for a sweep scenario**, used by both this module's
    CLI runner and the GUI's in-process route (``boulder.api.routes.sweep``).
    Goes through :class:`~boulder.simulation_worker.SimulationWorker` — the same
    class a plain "Run Simulation" uses — so a scenario's stored payload does
    not depend on which button produced it.

    It previously called ``build_network`` / ``run_streaming_simulation``
    directly here while the GUI route drove ``SimulationWorker`` and assembled
    its own payload. The two hand-built payloads had already drifted:
    ``updated_nodes``/``updated_connections`` (the nodes a staged solve
    synthesises during build, e.g. interface reservoirs) were real on the GUI
    path and hard-coded ``None`` here, so the same scenario drew a different
    network graph depending on its origin.

    ``converter_cls`` overrides which converter solves the scenario. The GUI
    passes ``app.state.converter_class`` — the same source ``/api/simulations``
    reads, set by the CLI at startup — because a host need not populate the
    entry-point plugin registry the same way; getting this wrong is what made
    a host's mechanism names unresolvable (parks4/boulder#135). Defaults to
    ``plugins.converter_class``, then :class:`DualCanteraConverter`.

    ``progress_cb`` is called with each :class:`SimulationProgress` poll while
    the solve runs — the GUI uses it to publish per-stage progress; the CLI
    passes nothing. The solved ``converter`` is returned (not discarded) so
    callers can build a :class:`~boulder.simulation_result.SimulationResult`
    from it or hand it to cache contributors — see :func:`run`'s ``on_solved``.

    ``stop_event``, when set mid-poll, requests that this scenario's solve
    stop -- the same :class:`~boulder.simulation_worker.SimulationWorker`
    cooperative-cancellation mechanism a plain "Run Simulation" uses (see
    ``SimulationWorker.stop_simulation``), not a second cancellation design.
    Raises, same as a genuine solve failure: the caller (the GUI sweep route)
    distinguishes the two by checking whether it itself requested the stop.
    """
    from .simulation_worker import SimulationWorker  # noqa: PLC0415 — cycle

    started = time.perf_counter()
    plugins = get_plugins()
    converter_cls = select_converter_class(converter_cls, plugins)
    conv = converter_cls(mechanism=mechanism or None, plugins=plugins)
    if config_path is not None:
        # The generated script names the file the run came from.
        conv._download_config_path = str(config_path)

    sim_t, dt = solver_window(config)
    worker = SimulationWorker()
    worker.start_simulation(conv, config, sim_t, dt)
    while True:
        progress = worker.get_progress()
        if progress_cb is not None:
            progress_cb(progress)
        if stop_event is not None and stop_event.is_set():
            worker.stop_simulation()
            break
        if progress.is_complete or progress.error_message:
            break
        time.sleep(poll_interval)
    if not progress.is_complete:
        raise RuntimeError(progress.error_message or "scenario solve failed")

    return gui_payload_from_progress(progress, started), conv.mechanism, conv


def gui_payload_from_progress(progress: Any, started: float) -> Dict[str, Any]:
    """Build the stored ``gui`` payload from a completed solve's progress.

    One builder for both sweep paths — the shape a scenario's HDF5 group is
    written from, and what the Scenario pane renders when the scenario is
    opened. Keep it the *only* place this dict is assembled: two copies is
    exactly how ``updated_nodes`` came to differ between GUI and CLI sweeps.
    """
    return {
        "status": "complete",
        "is_running": False,
        "is_complete": True,
        "error_message": None,
        "times": progress.times,
        "reactors_series": progress.reactors_series,
        # Same report generators a live "Run Simulation" uses, so a scenario
        # opened from the Scenario Pane shows the same Thermo tab content.
        "reactor_reports": progress.reactor_reports,
        "connection_reports": progress.connection_reports,
        "code_str": progress.code_str,
        "summary": progress.summary,
        "sankey_links": progress.sankey_links,
        "sankey_nodes": progress.sankey_nodes,
        # Wall-clock for build_network + solve, so a cached scenario can report
        # what it cost to produce.
        "elapsed_time": time.perf_counter() - started,
        # Nodes/edges the build synthesised (staged-solve interface reservoirs,
        # post-build hook edges) — needed for the graph to match the solver.
        "updated_nodes": progress.updated_nodes,
        "updated_connections": progress.updated_connections,
    }


def final_states_of(gui: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return each reactor's final ``{"T", "P", "X", "Y"}`` from a solved GUI payload.

    Read from ``reactors_series`` -- the same trajectory the Plots tab draws --
    so a chain's warm start (``initial: from_previous``) and its ``while:``
    condition see exactly the state the previous step ended in. Series without
    samples are skipped; a payload with no series yields ``{}``.
    """
    states: Dict[str, Dict[str, Any]] = {}
    for rid, series in (gui.get("reactors_series") or {}).items():
        if not isinstance(series, dict):
            continue
        temperatures = series.get("T") or []
        if not temperatures:
            continue
        state: Dict[str, Any] = {"T": float(temperatures[-1])}
        pressures = series.get("P") or []
        if pressures:
            state["P"] = float(pressures[-1])
        for fraction_key in ("X", "Y"):
            fractions = series.get(fraction_key)
            if isinstance(fractions, dict):
                state[fraction_key] = {
                    str(sp): float(vals[-1])
                    for sp, vals in fractions.items()
                    if isinstance(vals, (list, tuple)) and vals
                }
        states[str(rid)] = state
    return states


def stored_final_states(
    store_dir: Path, sid: str, identity: str
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Return :func:`final_states_of` a cached store entry, or ``None`` if unreadable.

    A cached (skipped) chain step still has to feed the next one, so its
    converged state is read back from the store instead of re-solved.
    """
    payload = scenario_store.read_entry(store_dir, sid, identity)
    return final_states_of(payload) if payload else None


def store_solved_scenario(
    store_dir: Path,
    sid: str,
    cfg: Dict[str, Any],
    config: Dict[str, Any],
    gui: Dict[str, Any],
    conv: Any,
    *,
    order: int,
    label: str,
    fingerprint: str,
    identity: str,
    mechanism: str,
    scenario_attrs: Optional[Callable[..., Any]] = None,
    on_solved: Optional[Callable[..., Any]] = None,
    warn: Optional[Callable[[str], None]] = None,
    source: Optional[scenario_store.RunSource] = None,
    alt_fingerprints: "Optional[Tuple[str, ...]]" = None,
) -> None:
    """Record one freshly solved run-set entry: attrs, the write, the host hook.

    The one store writer: every entry point's solve ends here (via
    :func:`run_set`). It was the tail of both sweep loops, which carried a copy
    each and drifted: one
    *assigned* the host hook's return over the sweep's own axis values where the
    other merged them, and they applied ``node_property_attrs`` on opposite
    sides of the hook. Same config, different stored attrs depending on which
    button you pressed. One function, so that cannot recur.

    Attr precedence, lowest to highest: the declarative sweep's axis values
    (the plot's natural X axis), then every node's own numeric properties
    (``in.<id>.<prop>``), then the host's ``scenario_attrs``. A host may pair a
    KPI with its display unit as ``(value, unit)``; the number becomes the attr
    and the unit is recorded separately, since HDF5 attrs are flat scalars.

    After the write, the registered cache contributors run for the entry (into
    its artifacts directory), then ``on_solved`` -- a host that called
    ``run_contributors`` from ``on_solved`` now runs its contributors twice.

    The hooks and contributors are best-effort: a KPI or artifact failure must
    not lose a scenario that already solved. *warn* receives the message; the default
    prints it.
    """
    say = warn or (lambda msg: print(msg, flush=True))

    entry_attrs: Dict[str, Any] = {
        key: value
        for key, value in sweep_point_of(cfg).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    entry_attrs.update(node_property_attrs(config))
    if scenario_attrs is not None:
        try:
            entry_attrs.update(scenario_attrs(sid, cfg, gui) or {})
        except Exception as exc:  # noqa: BLE001
            say(f"  WARNING: scenario_attrs hook failed for '{sid}': {exc}")

    entry_units: Dict[str, str] = {}
    for key, value in list(entry_attrs.items()):
        if isinstance(value, tuple):
            entry_attrs[key], entry_units[key] = value

    scenario_store.write_entry(
        store_dir,
        sid,
        gui_payload=gui,
        mechanism=mechanism,
        fingerprint=fingerprint,
        identity=identity,
        label=label,
        order=order,
        units=entry_units or None,
        extra_attrs=entry_attrs,
        source=source,
        alt_fingerprints=alt_fingerprints,
    )

    contributors = get_cache_contributor_registry().contributors
    if on_solved is None and not contributors:
        return
    # One SimulationResult, shared by the contributors and the host hook.
    try:
        from .simulation_result import make_simulation_result  # noqa: PLC0415

        simulation_result = make_simulation_result(conv, config)
    except Exception as exc:  # noqa: BLE001
        say(f"  WARNING: building the result failed for scenario '{sid}': {exc}")
        return
    # Same as a single run: artifacts land in the entry's directory, best-effort
    # (run_contributors logs a failing contributor and carries on).
    run_contributors(
        contributors,
        config,
        conv,
        simulation_result,
        fingerprint,
        store_artifacts_dir(store_dir, sid),
    )
    if on_solved is not None:
        try:
            on_solved(sid, config, conv, simulation_result, fingerprint, gui, mechanism)
        except Exception as exc:  # noqa: BLE001
            say(f"  WARNING: on_solved hook failed for scenario '{sid}': {exc}")


def notify_cached(
    on_cached: Optional[Callable[..., Any]],
    store_dir: Path,
    sid: str,
    config: Dict[str, Any],
    fingerprint: str,
    *,
    identity: str = "",
    warn: Optional[Callable[[str], None]] = None,
) -> None:
    """Tell the host's ``on_cached`` hook that *sid* was served from the store.

    Shared by every re-run path that skips a solve on a fingerprint hit; it is
    silent on a fresh solve, and may be called repeatedly for the same entry
    (once per re-run), so the host must handle it idempotently. The hook gets
    ``(scenario_id, config, fingerprint, artifacts_dir, computed_at)``;
    ``computed_at`` is the entry's original solve time (epoch seconds, ``0.0``
    when the entry records none). Best-effort, like ``on_solved``: a raising hook
    is reported through *warn* and never aborts the run.
    """
    if on_cached is None:
        return
    say = warn or (lambda msg: print(msg, flush=True))
    attrs = scenario_store.entry_attrs(store_dir, sid, identity) or {}
    try:
        on_cached(
            sid,
            config,
            fingerprint,
            store_artifacts_dir(store_dir, sid),
            float(attrs.get("computed_at", 0.0) or 0.0),
        )
    except Exception as exc:  # noqa: BLE001
        say(f"  WARNING: on_cached hook failed for scenario '{sid}': {exc}")


@dataclass
class EntryOutcome:
    """What one run-set entry produced: solved now, or read back from the store.

    ``gui`` is the stored payload (what the Scenario pane renders).
    """

    sid: str
    fingerprint: str
    cached: bool
    gui: Dict[str, Any]


def _classes(
    runner_cls: Optional[Any], converter_cls: Optional[Type[Any]]
) -> Tuple[Any, Type[DualCanteraConverter]]:
    """Return the runner and converter classes every entry point resolves alike."""
    from .runner import BoulderRunner  # noqa: PLC0415 — cycle

    runner_cls = runner_cls or BoulderRunner
    return runner_cls, select_converter_class(
        converter_cls or getattr(runner_cls, "converter_class", None)
    )


def prepare_entry(
    raw: Dict[str, Any],
    entry_id: str,
    *,
    runner_cls: Optional[Any] = None,
    converter_cls: Optional[Type[Any]] = None,
) -> Tuple[Dict[str, Any], str, str]:
    """Return ``(config, mechanism, fingerprint)`` that :func:`run_set` gives *entry_id*.

    The cache check's key: the same preparation and fingerprint as the solve, so a
    lookup agrees with what a run would store.
    """
    runner_cls, converter_cls = _classes(runner_cls, converter_cls)
    ((_, _, cfg),) = selected_entries(raw, {entry_id})
    return prepare_scenario(
        cfg, converter_mechanism_resolver(converter_cls), runner_cls
    )


def run_set(
    raw: Dict[str, Any],
    config_path: "Optional[str | Path]",
    *,
    only: Optional[Collection[str]] = None,
    use_cache: bool = True,
    converter_cls: Optional[Type[Any]] = None,
    runner_cls: Optional[Any] = None,
    resolve_mechanism: Optional[Callable[[str], str]] = None,
    scenario_attrs: Optional[Callable[..., Any]] = None,
    on_solved: Optional[Callable[..., Any]] = None,
    on_cached: Optional[Callable[..., Any]] = None,
    source: Optional[scenario_store.RunSource] = None,
    on_entry: Optional[Callable[[int, int, str, Dict[str, Any], bool], None]] = None,
    progress_cb: Optional[Callable[[str, Dict[str, Any], Any], None]] = None,
    stop_event: Optional[threading.Event] = None,
    log: Optional[Callable[[str], None]] = None,
) -> List[EntryOutcome]:
    """Solve and store a config's run-set: THE pipeline every entry point calls.

    CLI run, CLI sweep, GUI run, GUI sweep and the Python API all end here; a
    single run is a run set of one entry (``only={entry_id}``). Per entry:
    prepare (the runner's ``normalize`` + ``validate``), fingerprint, store hit
    (``on_cached``) or solve, store (:func:`store_solved_scenario`), hooks.

    ``raw`` is the resolved (``from:`` unfolded) config, scenario overlays
    already merged in (:func:`boulder.runset.merge_overlays`); it is not
    mutated. ``only`` restricts the run to those entry ids (the base entry
    :func:`~boulder.runset.base_entry_id` is always a valid id) and leaves the
    rest of the store untouched; without it the whole run-set runs and entries
    that left it are pruned. ``use_cache=False`` re-solves everything; for a
    whole run-set it also clears the store first.

    With no config path there is no store: the entries are solved and returned,
    nothing is written and no hook fires.

    ``on_entry(index, total, sid, config, cached)`` is called as each entry
    starts (``total`` is 0 for an open-ended chain); ``progress_cb(sid, config,
    progress)`` on each poll of a running solve; ``stop_event`` stops the run
    between entries and, in-flight, raises like a failed solve. ``log`` receives
    the progress lines (default: print). Returns one :class:`EntryOutcome` per
    entry, in order.
    """
    say = log or (lambda msg: print(msg, flush=True))
    plugins = get_plugins()
    scenario_attrs = scenario_attrs or getattr(plugins, "scenario_attrs", None)
    on_solved = on_solved or getattr(plugins, "on_scenario_solved", None)
    on_cached = on_cached or getattr(plugins, "on_scenario_cached", None)
    runner_cls, converter_cls = _classes(runner_cls, converter_cls)
    resolve = resolve_mechanism or converter_mechanism_resolver(converter_cls)

    store_dir = resolve_store_dir(raw, config_path)
    identity = scenario_store.config_identity(config_path)
    chain = sequential_of(raw) is not None
    cursor = RunSetCursor()
    entries: Any
    if only is None:
        entries = ((i, s, c) for i, (s, c) in enumerate(iter_run_set(raw, cursor)))
        total = run_set_size(raw)
    else:
        entries = selected_entries(raw, only)
        total = len(entries)
    if store_dir is not None:
        assert config_path is not None  # a store directory implies a config path
        if source is None:
            # One definition for the whole run-set: every entry points to it.
            source = scenario_store.build_source(raw, config_path)
        if not use_cache and only is None:
            scenario_store.clear(store_dir)
        store_dir.mkdir(parents=True, exist_ok=True)
    cached_fps = (
        scenario_store.fingerprints(store_dir, identity)
        if store_dir is not None and use_cache
        else {}
    )

    outcomes: List[EntryOutcome] = []
    for index, sid, cfg in entries:
        if stop_event is not None and stop_event.is_set():
            break
        config, mech_name, fingerprint = prepare_scenario(cfg, resolve, runner_cls)
        hit = store_dir is not None and cached_fps.get(sid) == fingerprint
        if on_entry is not None:
            on_entry(index, total, sid, config, hit)
        shown = f"scenario {index + 1}/{total or '?'} ({sid})"
        if hit:
            assert store_dir is not None
            say(f"{shown}: cached, skipped")
            # Display attrs still track the YAML (a reordered run-set) even
            # when the solve itself is skipped.
            scenario_store.update_display_attrs(store_dir, sid, label=sid, order=index)
            # A skipped chain step still seeds the next one.
            cursor.previous_states = stored_final_states(store_dir, sid, identity)
            notify_cached(
                on_cached,
                store_dir,
                sid,
                config,
                fingerprint,
                identity=identity,
                warn=say,
            )
            payload = scenario_store.read_entry(store_dir, sid, identity) or {}
            outcomes.append(EntryOutcome(sid, fingerprint, True, payload))
            continue
        say(shown)

        def _poll(
            progress: Any, _sid: str = sid, _cfg: Dict[str, Any] = config
        ) -> None:
            assert progress_cb is not None
            progress_cb(_sid, _cfg, progress)

        gui, resolved_mech, conv = solve_scenario(
            config,
            mech_name,
            converter_cls=converter_cls,
            progress_cb=None if progress_cb is None else _poll,
            stop_event=stop_event,
            config_path=config_path,
        )
        if store_dir is not None:
            # The post-build config (stream points the staged solver added)
            # describes the same solve: the entry answers to its key too.
            built = getattr(conv, "_last_config", None)
            alt = (
                scenario_fingerprint(
                    built,
                    normalized=True,
                    mechanism=mech_name,
                    resolve_mechanism=resolve,
                )
                if built
                else fingerprint
            )
            store_solved_scenario(
                store_dir,
                sid,
                cfg,
                config,
                gui,
                conv,
                order=index,
                label=sid,  # the `scenarios:` key is a scenario's only name
                fingerprint=fingerprint,
                identity=identity,
                mechanism=resolve(resolved_mech) if resolved_mech else resolved_mech,
                scenario_attrs=scenario_attrs,
                on_solved=on_solved,
                warn=say,
                source=source,
                alt_fingerprints=(alt,) if alt != fingerprint else None,
            )
        cursor.previous_states = final_states_of(gui)
        outcomes.append(EntryOutcome(sid, fingerprint, False, gui))

    stopped = stop_event is not None and stop_event.is_set()
    if store_dir is not None and only is None:
        if not chain:
            # The full intended set is known up front, however far the loop
            # got, so pruning stays correct for a stopped run.
            keep = {sid for sid, _ in expand_scenarios(raw)}
        elif not stopped:
            # A chain's intended set is only known once it has run to its end.
            keep = {o.sid for o in outcomes}
        else:
            keep = None
        stale = scenario_store.prune_entries(store_dir, keep) if keep else []
        if stale:
            say(f"Pruned {len(stale)} stale entr(ies): {', '.join(stale)}")
    return outcomes


def selected_entries(
    raw: Dict[str, Any], only: Collection[str]
) -> List[Tuple[int, str, Dict[str, Any]]]:
    """``(index, id, config)`` of the run-set entries named in *only*.

    An id the run-set does not declare is an error, except the base entry: a
    config whose run-set holds no unmodified base (a global sweep) still has
    one, the config without its run-set sections.
    """
    expanded = expand_scenarios(raw)
    known = {sid for sid, _ in expanded}
    base_id = base_entry_id(raw)
    unknown = set(only) - known - {base_id}
    if unknown:
        raise ValueError(f"Unknown scenario {sorted(unknown)[0]!r}")
    entries = [
        (i, sid, cfg) for i, (sid, cfg) in enumerate(expanded) if sid in set(only)
    ]
    if base_id in only and base_id not in known:
        base = {
            k: v for k, v in raw.items() if k != "scenarios" and k not in RUN_SET_KEYS
        }
        entries.insert(0, (0, base_id, base))
    return entries


def run(
    cfg_path: Path,
    *,
    setup: Optional[Callable[[], None]] = None,
    resolve_mechanism: Optional[Callable[[str], str]] = None,
    scenario_attrs: Optional[
        Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
    ] = None,
    on_solved: Optional[
        Callable[
            [str, Dict[str, Any], DualCanteraConverter, Any, str, Dict[str, Any], str],
            None,
        ]
    ] = None,
    on_cached: Optional[Callable[[str, Dict[str, Any], str, Path, float], None]] = None,
    runner_cls: Optional[Any] = None,
) -> Path:
    """Expand and solve *cfg_path*'s run-set into its collection store.

    A thin file-level wrapper over :func:`run_set`.

    Parameters
    ----------
    cfg_path : Path
        The STONE config declaring ``scenarios:`` / ``sweep:``.
    setup : callable, optional
        Called once before anything else — host process-level preparation
        (e.g. registering a mechanism directory on Cantera's search path).
    resolve_mechanism : callable, optional
        ``name -> str`` mapping a bare mechanism name to the identity stored
        and hashed (typically an absolute path). Defaults to the resolver
        derived from the converter class (see :func:`converter_mechanism_resolver`).
    scenario_attrs : callable, optional
        ``(scenario_id, merged_config, gui_payload) -> dict`` of extra scalar
        attributes written onto the scenario's HDF5 group after each solve —
        the per-run KPIs the Sweep Results plot reads (``t0_K``,
        ``final_X_<species>``, …). A value may be a bare number, or a
        ``(value, unit)`` tuple to also label the KPI's display unit; units
        are collected into a store-level ``units`` JSON attr (see
        :func:`~boulder.runset.node_property_attrs` for the input-side
        counterpart, recorded automatically without a host hook). Defaults to
        ``plugins.scenario_attrs``.
    on_solved : callable, optional
        ``(scenario_id, config, converter, simulation_result, fingerprint,
        gui_payload, mechanism) -> None`` called once per *freshly solved*
        scenario (skipped runs that hit the store cache do not fire it), right
        after the payload is written. Lets a host persist per-scenario
        artifacts keyed by the same ``fingerprint`` used elsewhere — e.g.
        running its own ``run_contributors`` so a downstream "Export" action
        can reuse the sweep's solve work instead of re-solving.
        Exceptions raised by the hook are caught and logged so one scenario's
        artifact failure does not abort the whole sweep. Defaults to
        ``plugins.on_scenario_solved``.
    on_cached : callable, optional
        ``(scenario_id, config, fingerprint, artifacts_dir, computed_at) ->
        None`` called once per scenario *served from the store* (the
        fingerprint matched, so nothing was solved and ``on_solved`` stays
        silent). ``artifacts_dir`` is the entry's existing artifacts directory
        and ``computed_at`` the entry's original solve time (epoch seconds), not
        the time of this run. Lets a host keep a side index complete when a
        model is re-run without changes. Fires on every re-run served from the
        store, possibly repeatedly for the same entry, so the host must handle
        repeated calls idempotently. Defaults to ``plugins.on_scenario_cached``;
        exceptions are caught and logged, like ``on_solved``.
    runner_cls : type, optional
        The :class:`~boulder.runner.BoulderRunner` subclass whose ``load``,
        ``normalize`` and ``validate`` prepare the config (default: the base
        runner).

    Returns
    -------
    Path
        The collection store written.
    """
    from .runner import BoulderRunner  # noqa: PLC0415 — cycle

    if setup is not None:
        setup()
    runner_cls = runner_cls or BoulderRunner
    raw = runner_cls.load(str(cfg_path))
    store_dir = resolve_store_dir(raw, cfg_path)
    assert store_dir is not None  # cfg_path is always set here
    # Incremental by default: keep the store and skip scenarios whose fingerprint
    # is unchanged. ``--no-cache`` (BOULDER_NO_CACHE) forces a full recompute.
    outcomes = run_set(
        raw,
        cfg_path,
        use_cache=not os.environ.get("BOULDER_NO_CACHE"),
        runner_cls=runner_cls,
        resolve_mechanism=resolve_mechanism,
        scenario_attrs=scenario_attrs,
        on_solved=on_solved,
        on_cached=on_cached,
    )
    n_cached = sum(o.cached for o in outcomes)
    print(
        f"Wrote {store_dir} ({len(outcomes)} scenarios; {n_cached} cached, "
        f"{len(outcomes) - n_cached} solved)",
        flush=True,
    )
    return store_dir


def main(argv: "list[str] | None" = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="STONE config with scenarios:/scenarios_sweep:")
    parser.add_argument("--no-plot", action="store_true", help="(accepted, ignored)")
    args = parser.parse_args(argv)
    run(Path(args.config).resolve())


if __name__ == "__main__":
    main()
