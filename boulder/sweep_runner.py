"""Generic scenario/sweep runner → composite collection store (for the GUI Run Sweep).

Invoked out-of-process by the ``/api/sweep`` routes for any config that declares
``scenarios:`` and/or ``sweep:``. It:

1. loads the raw config (``from:`` inheritance resolved),
2. expands the union run-set with :func:`boulder.runset.expand_scenarios`,
3. solves each run through the Boulder converter, and
4. writes each result as a **composite** payload into the collection store
   (``metadata.extra.scenario_store``, default ``<stem>_scenarios.h5``), one
   ``<scenario_id>/`` group per run,

printing ``scenario N/M`` per run so the sweep API can show progress. The
Scenario Pane then lists every run and opens each instantly.

Caching is incremental by default: each group carries the Boulder cache
fingerprint of its config (:func:`scenario_fingerprint`), and runs whose
fingerprint is unchanged are skipped. ``BOULDER_NO_CACHE`` (the Scenario
Pane's "Regenerate cache" action) recreates the store from scratch. Groups
whose scenario id left the run-set are pruned.

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
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Type

import h5py

from .cantera_converter import BoulderPlugins, DualCanteraConverter, get_plugins
from .config import normalize_config
from .payload_store import write_payload
from .runset import expand_scenarios, load_yaml_with_inheritance, resolve_store_path


def _mechanism_of(raw: Dict[str, Any]) -> str:
    gas = (raw.get("phases") or {}).get("gas") or {}
    return str(gas.get("mechanism") or "")


def _default_resolve_mechanism(plugins: BoulderPlugins) -> Callable[[str], str]:
    """Derive a mechanism-name resolver from ``plugins.converter_class``.

    Used whenever a caller doesn't pass ``resolve_mechanism`` explicitly, so a
    host that registers its own converter subclass (for its own mechanism
    search convention) gets consistent resolution everywhere -- the actual
    solve (:func:`_solve`), the cache fingerprint, and what's persisted to the
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


def _prepare(
    raw_cfg: Dict[str, Any],
    resolve_mechanism: Optional[Callable[[str], str]],
) -> Tuple[Dict[str, Any], str, str]:
    """Normalize a merged scenario config → ``(config, mechanism, fingerprint)``.

    The fingerprint (Boulder's cache key) lets the run skip scenarios that are
    already cached unchanged — computed without building/solving the network.
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


def _solve(
    config: Dict[str, Any], mechanism: str
) -> Tuple[Dict[str, Any], str, DualCanteraConverter]:
    """Solve one normalized scenario config → (gui_payload, mechanism, converter).

    The solved ``converter`` is returned (not discarded) so callers can build a
    :class:`~boulder.simulation_result.SimulationResult` from it or hand it to
    cache contributors — see the ``on_solved`` hook of :func:`run`.
    """
    plugins = get_plugins()
    converter_cls = plugins.converter_class or DualCanteraConverter
    conv = converter_cls(mechanism=mechanism or None, plugins=plugins)
    conv.build_network(config)

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
    results, code = conv.run_streaming_simulation(
        simulation_time=sim_t, time_step=dt, config=config
    )

    gui = {
        "status": "complete",
        "is_running": False,
        "is_complete": True,
        "error_message": None,
        "times": results.get("time", []),
        "reactors_series": results.get("reactors", {}),
        "reactor_reports": {},
        "connection_reports": {},
        "code_str": code,
        "summary": results.get("summary", []),
        "sankey_links": results.get("sankey_links"),
        "sankey_nodes": results.get("sankey_nodes"),
        "elapsed_time": None,
        "updated_nodes": None,
        "updated_connections": None,
    }
    return gui, conv.mechanism, conv


def existing_fingerprints(store: Path) -> Dict[str, str]:
    """Per-scenario fingerprints already in the store (group id → fingerprint).

    Shared cache primitive: any writer of a collection store (this runner, a
    host batch writer) reads its cache state through this.
    """
    found: Dict[str, str] = {}
    if not store.exists():
        return found
    with h5py.File(str(store), "r") as handle:
        for sid, node in handle.items():
            if isinstance(node, h5py.Group) and "payload_json" in node:
                fp = node.attrs.get("fingerprint")
                if fp:
                    found[sid] = str(fp)
    return found


def prune_stale_groups(store: Path, run_ids: set) -> list:
    """Delete groups whose scenario id is no longer in the run set.

    Renamed or removed scenarios would otherwise linger in the GUI's Scenario
    Pane forever (only ``--no-cache`` recreates the file). Returns the deleted
    group names.
    """
    with h5py.File(str(store), "a") as handle:
        stale = [
            sid
            for sid, node in handle.items()
            if isinstance(node, h5py.Group) and sid not in run_ids
        ]
        for sid in stale:
            del handle[sid]
    return stale


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
        ``final_X_<species>``, …).
    on_solved : callable, optional
        ``(scenario_id, config, converter, simulation_result, fingerprint,
        gui_payload, mechanism) -> None`` called once per *freshly solved*
        scenario (skipped runs that hit the store cache do not fire it), right
        after the payload is written. Lets a host persist per-scenario
        artifacts keyed by the same ``fingerprint`` used elsewhere — e.g.
        writing each scenario into the single-run result cache
        (``save_result`` + ``run_contributors``) so a downstream "Export"
        action can reuse the sweep's solve work instead of re-solving.
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
    _do_resolve = resolve_mechanism or _default_resolve_mechanism(plugins)
    _resolve = lambda name: _do_resolve(name) if name else name  # noqa: E731
    raw = load_yaml_with_inheritance(cfg_path)
    store = resolve_store_path(raw, cfg_path)
    assert store is not None  # cfg_path is always set here
    store.parent.mkdir(parents=True, exist_ok=True)

    # Incremental by default: keep the store and skip scenarios whose fingerprint
    # is unchanged. ``--no-cache`` (BOULDER_NO_CACHE) forces a full recompute.
    no_cache = bool(os.environ.get("BOULDER_NO_CACHE"))
    if no_cache and store.exists():
        store.unlink()
    cached_fps = {} if no_cache else existing_fingerprints(store)

    runs = expand_scenarios(raw)
    total = len(runs)
    run_ids = {sid for sid, _ in runs}
    mechanism = _mechanism_of(raw)
    n_cached = 0
    for i, (sid, cfg) in enumerate(runs):
        config, mech_name, fingerprint = _prepare(cfg, resolve_mechanism)
        label = str((cfg.get("metadata") or {}).get("scenario_name") or sid)
        if cached_fps.get(sid) == fingerprint:
            n_cached += 1
            print(f"scenario {i + 1}/{total} ({sid}): cached, skipped", flush=True)
            # Display attrs still track the YAML (reorderings / renamed labels)
            # even when the solve itself is skipped.
            with h5py.File(str(store), "a") as handle:
                attrs = handle[sid].attrs
                attrs["label"] = label
                attrs["order"] = int(i)
            continue
        print(f"scenario {i + 1}/{total} ({sid})", flush=True)
        gui, resolved_mech, conv = _solve(config, mech_name)
        stored_mech = _resolve(resolved_mech)
        write_payload(store, gui, stored_mech, group=sid, fresh=False)
        with h5py.File(str(store), "a") as handle:
            attrs = handle[sid].attrs
            attrs["label"] = label
            attrs["order"] = int(i)
            attrs["fingerprint"] = fingerprint
            attrs["computed_at"] = float(time.time())
            if scenario_attrs is not None:
                for key, value in (scenario_attrs(sid, cfg, gui) or {}).items():
                    attrs[key] = value
        if on_solved is not None:
            # Give the host a chance to persist per-scenario artifacts (e.g. a
            # calc-note bundle in the single-run result cache) keyed by this
            # scenario's fingerprint. Best-effort: a failure here must not abort
            # the remaining scenarios or the store write.
            try:
                from .simulation_result import make_simulation_result  # noqa: PLC0415

                simulation_result = make_simulation_result(conv, config)
                on_solved(
                    sid,
                    config,
                    conv,
                    simulation_result,
                    fingerprint,
                    gui,
                    stored_mech,
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  WARNING: on_solved hook failed for scenario '{sid}': {exc}",
                    flush=True,
                )

    stale = prune_stale_groups(store, run_ids)
    if stale:
        print(f"Pruned {len(stale)} stale scenario group(s): {', '.join(stale)}")

    with h5py.File(str(store), "a") as handle:
        handle.attrs["map_config"] = cfg_path.name
        handle.attrs["mechanism"] = _resolve(mechanism)
        handle.attrs["mechanism_name"] = Path(mechanism).name if mechanism else ""
        handle.attrs["created_at"] = float(time.time())
    print(
        f"Wrote {store} ({total} scenarios; {n_cached} cached, "
        f"{total - n_cached} solved)",
        flush=True,
    )
    return store


def main(argv: "list[str] | None" = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="STONE config with scenarios:/sweep:")
    parser.add_argument("--no-plot", action="store_true", help="(accepted, ignored)")
    args = parser.parse_args(argv)
    run(Path(args.config).resolve())


if __name__ == "__main__":
    main()
