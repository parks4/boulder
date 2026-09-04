"""Generic scenario/sweep runner → composite collection store (for the GUI Run Sweep).

Invoked out-of-process by the ``/api/sweep`` routes for any config that declares
``scenarios:`` and/or ``sweep:``. It:

1. loads the raw config (``from:`` inheritance resolved),
2. expands the union run-set with :func:`boulder.runset.expand_scenarios`,
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
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Type

from . import scenario_store
from .cantera_converter import BoulderPlugins, DualCanteraConverter, get_plugins
from .config import normalize_config
from .runset import (
    expand_scenarios,
    load_yaml_with_inheritance,
    node_property_attrs,
    resolve_store_dir,
    sweep_point_of,
)


def _mechanism_of(raw: Dict[str, Any]) -> str:
    gas = (raw.get("phases") or {}).get("gas") or {}
    return str(gas.get("mechanism") or "")


def _default_resolve_mechanism(plugins: BoulderPlugins) -> Callable[[str], str]:
    """Derive a mechanism-name resolver from ``plugins.converter_class``.

    Used whenever a caller doesn't pass ``resolve_mechanism`` explicitly, so a
    host that registers its own converter subclass (for its own mechanism
    search convention) gets consistent resolution everywhere -- the actual
    solve (:func:`solve_scenario`), the cache fingerprint, and what's persisted to the
    store -- without every call site needing to know about the plugin. Falls
    back to the base :class:`DualCanteraConverter`'s passthrough
    (``resolve_mechanism`` returns its argument unchanged) when no converter
    class is registered.

    Uses ``__new__`` rather than a normal constructor call: ``__init__``
    eagerly loads a real ``ct.Solution`` for the (possibly default)
    mechanism, which would be wasteful -- or outright fail for a host with no
    sensible default -- just to obtain a method reference. This assumes
    ``resolve_mechanism`` overrides don't depend on ``__init__``-set instance
    state (true for the base class, and any host override should preserve
    this too).
    """
    converter_cls: Type[DualCanteraConverter] = (
        plugins.converter_class or DualCanteraConverter
    )
    instance = converter_cls.__new__(converter_cls)
    return instance.resolve_mechanism


def scenario_fingerprint(
    raw_cfg: Dict[str, Any],
    *,
    extra: Optional[Dict[str, Any]] = None,
    resolve_mechanism: Optional[Callable[[str], str]] = None,
) -> str:
    """Boulder cache fingerprint for one merged (``from:``-resolved) scenario.

    THE fingerprint every scenario store uses — this runner and any host batch
    writer both call this; do not re-implement the cache key elsewhere.
    ``extra`` mixes caller-specific inputs into the hash (e.g. a save grid that
    lives outside the solved network config). ``resolve_mechanism`` maps a bare
    mechanism name to the identity actually hashed — defaults to the resolver
    derived from ``plugins.converter_class`` (see
    :func:`_default_resolve_mechanism`) so fingerprints match the store
    contents without the caller needing to pass its own resolver explicitly.
    """
    from .result_cache import compute_fingerprint  # noqa: PLC0415

    plugins = get_plugins()
    config = normalize_config(copy.deepcopy(raw_cfg), plugins=plugins)
    mechanism = _mechanism_of(raw_cfg)
    if mechanism:
        resolve_mechanism = resolve_mechanism or _default_resolve_mechanism(plugins)
        mechanism = resolve_mechanism(mechanism)
    return compute_fingerprint(config, mechanism=mechanism, extra=extra)


def prepare_scenario(
    raw_cfg: Dict[str, Any],
    resolve_mechanism: Optional[Callable[[str], str]],
) -> Tuple[Dict[str, Any], str, str]:
    """Normalize a merged scenario config → ``(config, mechanism, fingerprint)``.

    The fingerprint (Boulder's cache key) lets the run skip scenarios that are
    already cached unchanged — computed without building/solving the network.
    Public: shared with any out-of-process caller that needs to solve exactly
    one scenario the same way this runner does (e.g. an "Export" GUI action
    solving a cache-miss scenario on demand).
    """
    from .result_cache import compute_fingerprint  # noqa: PLC0415

    plugins = get_plugins()
    config = normalize_config(copy.deepcopy(raw_cfg), plugins=plugins)
    mechanism = _mechanism_of(raw_cfg)
    if mechanism:
        resolve_mechanism = resolve_mechanism or _default_resolve_mechanism(plugins)
        hashed = resolve_mechanism(mechanism)
    else:
        hashed = mechanism
    fingerprint = compute_fingerprint(config, mechanism=hashed)
    return config, mechanism, fingerprint


def solver_window(config: Dict[str, Any]) -> Tuple[float, float]:
    """Return ``(simulation_time, time_step)`` for one scenario's solve.

    Shared so the GUI and CLI sweeps cannot disagree about how long a scenario
    runs — a silent divergence here would make the same scenario produce
    different trajectories depending on which button solved it.
    """
    settings = config.get("settings") or {}
    sim_t = float(settings.get("end_time") or 0.0)
    if sim_t <= 0.0:
        sim_t = 1.0
        if not settings.get("solver"):
            # A solver grid (e.g. from a host config transform) overrides the
            # nominal end_time; without either, flag the silent 1 s default.
            print(
                "  WARNING: settings.end_time missing — defaulting to 1.0 s. "
                "Declare settings.end_time (or a settings.solver grid) for a "
                "meaningful trajectory.",
                flush=True,
            )
    dt = float(settings.get("dt") or 0.0) or (sim_t / 10.0)
    return sim_t, dt


def solve_scenario(
    config: Dict[str, Any],
    mechanism: str,
    *,
    converter_cls: Optional[Type[Any]] = None,
    progress_cb: Optional[Callable[[Any], None]] = None,
    poll_interval: float = 0.05,
    stop_event: Optional[threading.Event] = None,
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
    converter_cls = converter_cls or plugins.converter_class or DualCanteraConverter
    conv = converter_cls(mechanism=mechanism or None, plugins=plugins)

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
) -> None:
    """Record one freshly solved run-set entry: attrs, the write, the host hook.

    The tail of both sweep loops -- the GUI's (``api/routes/sweep.py``) and this
    module's headless one. They used to carry a copy each and drifted: one
    *assigned* the host hook's return over the sweep's own axis values where the
    other merged them, and they applied ``node_property_attrs`` on opposite
    sides of the hook. Same config, different stored attrs depending on which
    button you pressed. One function, so that cannot recur.

    Attr precedence, lowest to highest: the declarative sweep's axis values
    (the plot's natural X axis), then every node's own numeric properties
    (``in.<id>.<prop>``), then the host's ``scenario_attrs``. A host may pair a
    KPI with its display unit as ``(value, unit)``; the number becomes the attr
    and the unit is recorded separately, since HDF5 attrs are flat scalars.

    Both hooks are best-effort: a KPI or artifact failure must not lose a
    scenario that already solved. *warn* receives the message; the default
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
    )

    if on_solved is not None:
        try:
            from .simulation_result import make_simulation_result  # noqa: PLC0415

            on_solved(
                sid,
                config,
                conv,
                make_simulation_result(conv, config),
                fingerprint,
                gui,
                mechanism,
            )
        except Exception as exc:  # noqa: BLE001
            say(f"  WARNING: on_solved hook failed for scenario '{sid}': {exc}")


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
) -> Path:
    """Expand and solve *cfg_path*'s run-set into its collection store.

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
        derived from ``plugins.converter_class`` (see
        :func:`_default_resolve_mechanism`).
    scenario_attrs : callable, optional
        ``(scenario_id, merged_config, gui_payload) -> dict`` of extra scalar
        attributes written onto the scenario's HDF5 group after each solve —
        the per-run KPIs the Sweep Results plot reads (``t0_K``,
        ``final_X_<species>``, …). A value may be a bare number, or a
        ``(value, unit)`` tuple to also label the KPI's display unit; units
        are collected into a store-level ``units`` JSON attr (see
        :func:`~boulder.runset.node_property_attrs` for the input-side
        counterpart, recorded automatically without a host hook).
    on_solved : callable, optional
        ``(scenario_id, config, converter, simulation_result, fingerprint,
        gui_payload, mechanism) -> None`` called once per *freshly solved*
        scenario (skipped runs that hit the store cache do not fire it), right
        after the payload is written. Lets a host persist per-scenario
        artifacts keyed by the same ``fingerprint`` used elsewhere — e.g.
        running its own ``run_contributors`` so a downstream "Export" action
        can reuse the sweep's solve work instead of re-solving.
        Exceptions raised by the hook are caught and logged so one scenario's
        artifact failure does not abort the whole sweep.

    Returns
    -------
    Path
        The collection store written.
    """
    if setup is not None:
        setup()
    plugins = get_plugins()
    # Fall back to the host-registered hooks so a plain `python -m
    # boulder.sweep_runner` records the same KPI attrs and persists the same
    # per-scenario artifacts as the GUI's in-process sweep, which reads these
    # straight off the plugin registry. An explicit argument always wins.
    if scenario_attrs is None:
        scenario_attrs = getattr(plugins, "scenario_attrs", None)
    if on_solved is None:
        on_solved = getattr(plugins, "on_scenario_solved", None)
    _do_resolve = resolve_mechanism or _default_resolve_mechanism(plugins)
    _resolve = lambda name: _do_resolve(name) if name else name  # noqa: E731
    raw = load_yaml_with_inheritance(cfg_path)
    store_dir = resolve_store_dir(raw, cfg_path)
    assert store_dir is not None  # cfg_path is always set here
    identity = scenario_store.config_identity(cfg_path)
    store_dir.mkdir(parents=True, exist_ok=True)

    # Incremental by default: keep the store and skip scenarios whose fingerprint
    # is unchanged. ``--no-cache`` (BOULDER_NO_CACHE) forces a full recompute.
    no_cache = bool(os.environ.get("BOULDER_NO_CACHE"))
    if no_cache:
        scenario_store.clear(store_dir)
        store_dir.mkdir(parents=True, exist_ok=True)
    cached_fps = {} if no_cache else scenario_store.fingerprints(store_dir, identity)

    runs = expand_scenarios(raw)
    total = len(runs)
    run_ids = {sid for sid, _ in runs}
    n_cached = 0
    for i, (sid, cfg) in enumerate(runs):
        config, mech_name, fingerprint = prepare_scenario(cfg, resolve_mechanism)
        # The `scenarios:` key is a scenario's only name -- no separate label.
        label = sid
        if cached_fps.get(sid) == fingerprint:
            n_cached += 1
            print(f"scenario {i + 1}/{total} ({sid}): cached, skipped", flush=True)
            # Display attrs still track the YAML (a reordered run-set) even
            # when the solve itself is skipped.
            scenario_store.update_display_attrs(store_dir, sid, label=label, order=i)
            continue
        print(f"scenario {i + 1}/{total} ({sid})", flush=True)
        gui, resolved_mech, conv = solve_scenario(config, mech_name)
        stored_mech = _resolve(resolved_mech)
        store_solved_scenario(
            store_dir,
            sid,
            cfg,
            config,
            gui,
            conv,
            order=i,
            label=label,
            fingerprint=fingerprint,
            identity=identity,
            mechanism=stored_mech,
            scenario_attrs=scenario_attrs,
            on_solved=on_solved,
        )

    stale = scenario_store.prune_entries(store_dir, run_ids)
    if stale:
        print(f"Pruned {len(stale)} stale entr(ies): {', '.join(stale)}")

    # No store-level finalisation: each entry carries its own mechanism, units
    # and computed_at, written the moment it solved.
    print(
        f"Wrote {store_dir} ({total} scenarios; {n_cached} cached, "
        f"{total - n_cached} solved)",
        flush=True,
    )
    return store_dir


def main(argv: "list[str] | None" = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="STONE config with scenarios:/sweep:")
    parser.add_argument("--no-plot", action="store_true", help="(accepted, ignored)")
    args = parser.parse_args(argv)
    run(Path(args.config).resolve())


if __name__ == "__main__":
    main()
