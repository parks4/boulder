"""STONE run-set primitives: inline ``scenarios:`` / ``scenarios_sweep:`` expansion.

A STONE YAML may declare parameter variations inline (STONE_SPECIFICATIONS.md,
Section 14), avoiding a glob of overlay files:

``scenarios:``
    Mapping ``{id: overlay-subtree}``. Each value is a STONE subtree
    (``metadata``/``settings``/``network``/…) deep-merged onto the base via
    :func:`deep_merge` (which supports id-keyed ``nodes``/``connections``
    merging) — exactly the overlay a standalone ``from:`` file carries. The
    mapping **key is the scenario id**. (A *list*-valued top-level
    ``scenarios:`` is the legacy pre-mapping dialect and is rejected —
    see :func:`expand_scenarios`.)

``scenarios_sweep:``
    The run-set block. Either grid axes -- ``{axis_name: {path, values |
    min/max/num}}``, crossed as a Cartesian product, at the top level
    (expanded on the base) or *inside* a ``scenarios:`` entry (expanded on
    that scenario only) -- or one sequential chain: ``for:`` (walk a list of
    values in order) / ``while:`` (repeat an ``update`` while a ``condition``
    read from the previous result holds), optionally warm-started with
    ``initial: from_previous``. The legacy spellings ``sweep:``/``sweeps:``
    are renamed on load with a warning (:func:`canonicalize_run_set_keys`).

This module is the reference implementation of those semantics: the Run Sweep
API sizes run-sets with :func:`run_set_size`, and both sweep loops (the GUI
route and :mod:`boulder.sweep_runner`) pull their points from
:func:`iter_run_set` -- eager for grids and overlays (:func:`expand_scenarios`),
lazy for a chain, whose next point depends on the previous solve. Host packages
should call these functions rather than re-implementing the rules.

Everything here is pure config manipulation — no solving, no I/O beyond
:func:`load_yaml_with_inheritance` — and host-agnostic: host-specific naming
(axis-label symbols) and schema knowledge enter only through the
``plugins.sweep_symbols`` registry and the ``schema_entry`` hook.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

#: Scenario id for the unmodified base config's own run-set entry — whether
#: that entry comes from a ``scenarios:`` mapping (see :func:`expand_scenarios`)
#: or *is* the whole run-set (the N=1 case, no ``scenarios:`` block at all).
#: One name for both so a plain Run Simulation and a Run Sweep of the same
#: config always agree on where the result lives. Reserved: a host must
#: reject this as a user-authored scenario id (see
#: ``scenario_editor._validate_id``) since a config could otherwise define its
#: own "BASELINE" overlay that collides with this synthesized entry.
BASELINE_SCENARIO_ID = "BASELINE"

# ---------------------------------------------------------------------------
# Deep merge with id-keyed list support (the STONE overlay merge).
# ---------------------------------------------------------------------------


def _is_id_based_list(lst: list) -> bool:
    """Return whether *lst* is a non-empty list of dicts that all carry ``id``."""
    return bool(lst) and all(isinstance(item, dict) and "id" in item for item in lst)


def _merge_lists_by_id(base_list: list, overlay_list: list) -> list:
    """Merge two id-keyed lists element-wise by ``id``.

    Elements present in both lists are deep-merged; base-only elements are
    kept; overlay-only elements are appended (in overlay order).
    """
    overlay_by_id = {item["id"]: item for item in overlay_list}
    result: list = []
    used_ids: set = set()

    for base_item in base_list:
        item_id = base_item["id"]
        if item_id in overlay_by_id:
            merged = deep_merge(base_item, overlay_by_id[item_id])
            result.append(merged)
            used_ids.add(item_id)
        else:
            result.append(copy.deepcopy(base_item))

    for overlay_item in overlay_list:
        item_id = overlay_item["id"]
        if item_id not in used_ids:
            result.append(copy.deepcopy(overlay_item))

    return result


def deep_merge(base: dict, overlay: dict) -> dict:
    """Deep-merge *overlay* into *base*. Overlay values win.

    Dicts merge recursively. Lists whose elements all carry an ``id`` field
    (``nodes``, ``connections``, stage lists) merge element-wise by id instead
    of being replaced wholesale — the STONE overlay semantics.

    Parameters
    ----------
    base : dict
        The base dictionary.
    overlay : dict
        The overlay dictionary (overrides take precedence).

    Returns
    -------
    dict
        A new dictionary with the merged result.
    """
    result = copy.deepcopy(base)
    for key, overlay_value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(overlay_value, dict)
        ):
            result[key] = deep_merge(result[key], overlay_value)
        elif (
            key in result
            and isinstance(result[key], list)
            and isinstance(overlay_value, list)
            and _is_id_based_list(result[key])
            and _is_id_based_list(overlay_value)
        ):
            result[key] = _merge_lists_by_id(result[key], overlay_value)
        else:
            result[key] = copy.deepcopy(overlay_value)
    return result


def _load_yaml_with_inheritance(path: "str | Path") -> dict:
    """Load a STONE YAML with optional ``from:`` inheritance (keys as written).

    If a top-level ``from`` key is present, that file is loaded first
    (recursively) and deep-merged with the current file content (excluding
    ``from``). Relative ``from`` paths are resolved against the current file
    directory.

    The ``scenarios:`` directive is **not inherited**: a named scenario mapping
    declares *this* file's run-set, so a parent's scenarios must not leak into
    a child (which would re-run them against the child's base). The
    ``scenarios_sweep:`` block **is** inherited — a child overlay legitimately
    re-runs the parent's parameter sweep with overrides (e.g. a different
    mechanism).
    """
    from ruamel.yaml import YAML  # noqa: PLC0415 — heavy import kept lazy

    yaml = YAML()
    yaml.preserve_quotes = True
    path = Path(path)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = yaml.load(f)

    if data is None:
        return {}

    data_dict = dict(data)
    from_path = data_dict.get("from")
    if not from_path:
        return data_dict

    overlay = copy.deepcopy(data_dict)
    overlay.pop("from", None)

    parent_path = (path.parent / str(from_path)).resolve()
    base = _load_yaml_with_inheritance(parent_path)
    base.pop("scenarios", None)  # the named run-set is not inherited (sweeps are)
    return deep_merge(base, overlay)


def load_yaml_with_inheritance(path: "str | Path") -> dict:
    """Load a STONE YAML (``from:`` resolved) with its run-set block canonicalized.

    See :func:`_load_yaml_with_inheritance` for the inheritance rules and
    :func:`canonicalize_run_set_keys` for the legacy ``sweep:``/``sweeps:``
    rename (one warning per legacy key, on the merged result only).
    """
    data = _load_yaml_with_inheritance(path)
    canonicalize_run_set_keys(data)
    return data


# ---------------------------------------------------------------------------
# Sweep-axis primitives.
# ---------------------------------------------------------------------------


#: The canonical top-level key of a config's inline run-set block.
RUN_SET_KEY = "scenarios_sweep"

#: Former spellings of :data:`RUN_SET_KEY`. Still loaded -- renamed in place
#: with a warning by :func:`canonicalize_run_set_keys` -- so a file authored
#: against an older release keeps working while the name to migrate to is one.
LEGACY_RUN_SET_KEYS: Tuple[str, ...] = ("sweep", "sweeps")

#: Every key a run-set block may sit under, canonical first.
RUN_SET_KEYS: Tuple[str, ...] = (RUN_SET_KEY, *LEGACY_RUN_SET_KEYS)

#: Keys inside a ``scenarios_sweep:`` block that configure the run-set rather
#: than declare a grid axis. Filtered out of every axis-iterating code path.
SWEEP_RESERVED_KEYS = frozenset({"runner", "for", "while"})

#: The two sequential (chain) run-set forms -- see :func:`sequential_of`.
SEQUENTIAL_KINDS: Tuple[str, ...] = ("for", "while")


def canonicalize_run_set_keys(raw: Any) -> List[str]:
    """Rename legacy run-set keys in *raw* to :data:`RUN_SET_KEY`, in place.

    ``sweep:``/``sweeps:`` become ``scenarios_sweep:`` (one warning per key,
    naming the replacement). A top-level ``continuation:`` block is left as it
    is -- it still drives the headless
    :meth:`boulder.runner.BoulderRunner.run_continuation` -- but is warned
    about too: Run Sweep does not execute it; ``scenarios_sweep.while`` is its
    run-set form (STONE_SPECIFICATIONS.md, Section 14). Each ``scenarios:``
    overlay is walked as well, since its inner block follows the same rules.

    Returns the legacy keys found (empty for an already-canonical file). Safe
    on non-dict input (returns ``[]``).
    """
    if not isinstance(raw, dict):
        return []
    found: List[str] = []
    for legacy in LEGACY_RUN_SET_KEYS:
        if legacy not in raw:
            continue
        found.append(legacy)
        block = raw.pop(legacy)
        if RUN_SET_KEY in raw:
            logger.warning(
                "'%s:' is a legacy spelling of '%s:' and was ignored because the "
                "file already declares '%s:'. Remove the legacy block.",
                legacy,
                RUN_SET_KEY,
                RUN_SET_KEY,
            )
            continue
        raw[RUN_SET_KEY] = block
        logger.warning(
            "'%s:' is a legacy spelling of the run-set block and was read as "
            "'%s:'. Rename it in the YAML (STONE_SPECIFICATIONS.md, Section 14).",
            legacy,
            RUN_SET_KEY,
        )
    if "continuation" in raw:
        found.append("continuation")
        logger.warning(
            "'continuation:' is legacy: Run Sweep does not execute it (only the "
            "headless BoulderRunner.run_continuation does). Declare the chain as "
            "'%s: {while: ...}' instead (STONE_SPECIFICATIONS.md, Section 14).",
            RUN_SET_KEY,
        )
    scenarios = raw.get("scenarios")
    if isinstance(scenarios, dict):
        for overlay in scenarios.values():
            if isinstance(overlay, dict):
                found.extend(
                    f"scenarios.{k}" for k in canonicalize_run_set_keys(overlay)
                )
    return found


def run_set_block(block: dict) -> dict:
    """Return a config/overlay's run-set block (``{}`` when absent or malformed).

    Reads :data:`RUN_SET_KEY` first, then the legacy spellings -- silently: the
    warning belongs to load time (:func:`canonicalize_run_set_keys`), not to
    an accessor the availability endpoint polls every second.
    """
    for key in RUN_SET_KEYS:
        raw = block.get(key)
        if raw is not None:
            return raw if isinstance(raw, dict) else {}
    return {}


def _strip_run_set_keys(config: dict) -> None:
    """Drop the run-set block (every spelling) from *config*, in place."""
    for key in RUN_SET_KEYS:
        config.pop(key, None)


def sweeps_of(block: dict) -> dict:
    """Return a config/overlay's grid **axes** (``{axis_name: axis_spec}``).

    Reserved keys (:data:`SWEEP_RESERVED_KEYS` -- the host ``runner`` and the
    ``for:``/``while:`` chain) are stripped, so every caller that treats the
    result as axes stays correct as non-axis configuration is added.
    """
    return {
        k: v for k, v in run_set_block(block).items() if k not in SWEEP_RESERVED_KEYS
    }


def sweep_runner_of(block: dict) -> Optional[str]:
    """Return a config's declared host sweep runner, or ``None``.

    ``scenarios_sweep.runner`` is a dotted ``"package.module:callable"``
    reference to a host function that produces the run-set itself. It predates
    the ``for:``/``while:`` chains (:func:`sequential_of`), which now cover the
    sequential, warm-started case declaratively; a runner remains for run-sets
    that not even a chain can express.

    Declaring it in the config is deliberate: Boulder used to *guess*, running
    any file literally named ``run_sweep.py`` sitting next to the config. That
    coupled behaviour to a filename, was invisible in the config, and silently
    stopped working when Run Sweep moved in-process. An explicit dotted path is
    resolvable, greppable, and testable.
    """
    runner = run_set_block(block).get("runner")
    return str(runner) if runner else None


def sweep_axis_values(axis_spec: dict) -> list:
    """Return the explicit list of sweep values for one axis spec.

    Two forms are supported:

    * ``values: [v0, v1, ...]`` — an explicit list (returned as-is).
    * ``min`` / ``max`` / ``num`` — a generated, evenly spaced range.
      ``num`` (alias ``npoints``) is the number of points, inclusive of both
      endpoints.  Spacing is linear by default; set ``spacing: log`` for a
      geometric (log-spaced) range.  Generated values are rounded to remove
      floating-point noise so scenario ids stay clean.

    An explicit ``values`` list takes precedence when both are present.
    Returns an empty list when the spec declares neither form.
    """
    if axis_spec.get("values") is not None:
        return list(axis_spec["values"])

    if axis_spec.get("min") is None or axis_spec.get("max") is None:
        return []

    import numpy as np  # noqa: PLC0415

    lo = float(axis_spec["min"])
    hi = float(axis_spec["max"])
    num = axis_spec.get("num", axis_spec.get("npoints"))
    if num is None:
        raise ValueError("sweep range requires 'num' (or 'npoints')")
    num = int(num)
    if num < 1:
        raise ValueError(f"sweep 'num' must be >= 1, got {num}")

    spacing = str(axis_spec.get("spacing", "linear")).lower()
    if spacing in ("linear", "lin", "linspace"):
        values = np.linspace(lo, hi, num)
    elif spacing in ("log", "logspace", "geometric"):
        if lo <= 0 or hi <= 0:
            raise ValueError("log-spaced sweep requires positive 'min' and 'max'")
        values = np.logspace(np.log10(lo), np.log10(hi), num)
    else:
        raise ValueError(f"unknown sweep spacing {spacing!r}; use 'linear' or 'log'")

    return [round(float(v), 10) for v in values]


def _sweep_size(sweeps_block: dict) -> int:
    """Cartesian-product size of a sweep block's axes (0 for an empty block).

    Never raises: a malformed axis counts as 0 so availability endpoints can
    report a size for any config; :func:`expand_scenarios` is where malformed
    axes fail loudly.
    """
    if not isinstance(sweeps_block, dict) or not sweeps_block:
        return 0
    total = 1
    for axis in sweeps_block.values():
        try:
            n = len(sweep_axis_values(axis)) if isinstance(axis, dict) else 0
        except ValueError:
            n = 0
        total *= max(n, 0)
    return total


def run_set_size(raw: Dict[str, Any]) -> int:
    """Return the union run-set size of a config's ``scenarios:``/``scenarios_sweep:``.

    The unmodified base config (:data:`BASELINE_SCENARIO_ID`) ⊎ global sweep
    points ⊎ each ``scenarios:`` entry (its inner sweep, else 1) ⊎ a ``for:``
    chain's values — the same union semantics :func:`iter_run_set` implements,
    computed without deep-merging or resolving sweep paths (cheap enough for an
    availability endpoint). A ``while:`` chain contributes 0: its length is only
    known once its condition trips.
    """
    scenarios = raw.get("scenarios") or {}
    scenarios = scenarios if isinstance(scenarios, dict) else {}
    total = 1 if scenarios else 0
    total += _sweep_size(sweeps_of(raw))
    for overlay in scenarios.values():
        inner = sweeps_of(overlay or {})
        total += _sweep_size(inner) if inner else 1
    try:
        chain = sequential_block_of(raw)
        if chain is not None and chain[0] == "for":
            total += len(sweep_axis_values(chain[1]))
    except ValueError:
        pass  # malformed: counts 0 here, fails loudly in sequential_of
    return total


# ---------------------------------------------------------------------------
# Result-store layout: one file per run-set entry.
# ---------------------------------------------------------------------------
#
# A run-set's results live in a directory, one HDF5 file per entry, rather than
# one file with a group per entry. HDF5 is single-writer, and every solve --
# a whole sweep or a single run -- writes here while the GUI polls the same
# location for reading; per-entry files remove write contention, confine a
# partial write to one entry, make invalidating one entry a file delete, and
# leave room to solve entries in parallel later.
#
#     <store_dir>/
#         BASELINE.h5 | <scenario_id>.h5
#         artifacts/<scenario_id>/...        host cache-contributor files

#: Characters that are unsafe in a filename on some supported platform, plus
#: the HDF5 path separator (an id containing ``/`` would silently become a
#: *nested* group rather than an entry).
_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_.-]")

#: Stems Windows refuses to use as filenames regardless of extension.
_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def store_entry_name(scenario_id: str) -> str:
    """Return a filesystem- and HDF5-safe stem for *scenario_id*.

    Scenario ids reach us straight from YAML ``scenarios:`` keys and sweep-point
    labels, neither of which passes through ``scenario_editor._validate_id``
    (that guards only GUI-authored ids). They now become *filenames*, so they
    must be sanitised centrally here.

    Sanitising alone would let distinct ids collide (``a/b`` and ``a_b`` mapping
    to one file, silently sharing results), so whenever the safe form differs
    from the original -- or collides with a Windows reserved stem -- a short
    digest of the original is appended. Ids that are already safe (the
    overwhelming majority) are used verbatim, keeping the directory readable.
    """
    safe = _UNSAFE_ID_CHARS.sub("_", scenario_id).strip(". ") or "entry"
    if safe != scenario_id or safe.upper() in _RESERVED_STEMS:
        return f"{safe}-{_sha8(scenario_id)}"
    return safe


def resolve_store_dir(
    raw: Dict[str, Any], config_path: "Optional[str | Path]"
) -> Optional[Path]:
    """Return the directory holding this config's per-entry result files.

    Declared via ``metadata.extra.cache_store`` (``scenario_store`` is still
    honoured as its former name), resolved relative to the config when not
    absolute. Otherwise it is a subdirectory of the cache root that
    :func:`boulder.result_cache.cache_dir_for` picks -- normally
    ``<config_dir>/.boulder-cache/<stem>/``, so results sit in the one already
    git-ignored place for derived data instead of beside the YAML.

    ``$BOULDER_CACHE_DIR`` makes that root *shared across configs*, which a
    name-addressed store cannot tolerate on its own: two configs both named
    ``case.yaml`` would otherwise share a directory and read each other's
    entries. In that case the config's absolute path is folded into the
    subdirectory name. (A store is additionally stamped with the config it
    belongs to, so a mismatch rebuilds rather than serving another config's
    results -- see :mod:`boulder.scenario_store`.)

    ``None`` when *config_path* is unset — there is no config to resolve
    against.
    """
    if not config_path:
        return None
    cfg = Path(config_path).resolve()
    extra = (raw.get("metadata") or {}).get("extra") or {}
    rel = extra.get("cache_store") or extra.get("scenario_store")
    if rel:
        p = Path(rel)
        return p if p.is_absolute() else cfg.parent / p

    from .result_cache import cache_dir_for  # noqa: PLC0415 — avoid import cycle

    root = cache_dir_for(str(cfg))
    if root is None:  # pragma: no cover — cfg is set, so cache_dir_for resolves
        return None
    name = cfg.stem
    if os.environ.get("BOULDER_CACHE_DIR", "").strip():
        # Shared root: disambiguate by the config's full path.
        name = f"{cfg.stem}-{_sha8(str(cfg))}"
    return root / name


def store_entry_path(store_dir: Path, scenario_id: str) -> Path:
    """Return the result file for *scenario_id* inside *store_dir*."""
    return store_dir / f"{store_entry_name(scenario_id)}.h5"


def store_artifacts_dir(store_dir: Path, scenario_id: str) -> Path:
    """Return the host-contributor artifacts directory for *scenario_id*.

    Files, not HDF5 datasets: contributors write bundles (JSON + figure PNGs),
    which stay far easier to produce and consume as real files.
    """
    return store_dir / "artifacts" / store_entry_name(scenario_id)


# ---------------------------------------------------------------------------
# Run-set expansion.
# ---------------------------------------------------------------------------


def base_entry_id(raw: Dict[str, Any]) -> str:
    """Return the store id the *unmodified base* run is written under.

    Always :data:`BASELINE_SCENARIO_ID`, whether the config declares
    ``scenarios:`` or is itself the whole (N=1) run-set. Mirrors the naming
    :func:`expand_scenarios` gives the base entry, which is the whole point:
    both paths that can solve the base must land on the same name.

    They did not, historically. A sweep took the name from
    :func:`expand_scenarios` (``BASELINE``) while a plain Run Simulation
    defaulted to a different id, so the same result was stored twice under two
    names -- the pane grew a phantom row while the authored ``BASELINE`` row
    still read "Not computed yet".

    A global ``sweep:`` without ``scenarios:`` deliberately does **not** count:
    there the run-set is the sweep points themselves (ids prefixed
    ``BASELINE__``) and no unmodified-base entry is emitted at all, so *this*
    function's return value is moot for that config -- nothing gets written
    under the plain ``BASELINE`` name.
    """
    return BASELINE_SCENARIO_ID


def expand_scenarios(
    base_raw: dict,
    *,
    symbols: Optional[Mapping[str, str]] = None,
    schema_entry: Optional[Callable[[str], Any]] = None,
) -> List[Tuple[str, dict]]:
    """Expand a STONE YAML's inline ``scenarios:`` / ``sweep:`` blocks.

    **Union semantics** (not a global cross-product): the run set is the
    base's global-sweep points **⊎** each ``scenarios:`` entry (each expanded
    across its *own* inner sweep if it declares one). A top-level sweep and
    the scenarios do not cross-multiply.

    When neither block is present, returns a single ``(scenario_id, base)``
    tuple using :data:`BASELINE_SCENARIO_ID`. A ``for:``/``while:`` chain is
    deliberately *not* expanded here -- its points depend on the previous solve
    -- so a config declaring only a chain also yields that single base tuple;
    :func:`iter_run_set` is the entry point that knows about chains.

    Parameters
    ----------
    base_raw : dict
        The raw (``from:``-resolved) config. Not mutated.
    symbols : Mapping[str, str], optional
        Axis-name/path-leaf → symbol mapping used to label sweep points in
        scenario ids (e.g. ``diameter`` → ``TF_D`` gives ``BASELINE__TF_D=0.03``).
        Defaults to the host-registered ``plugins.sweep_symbols`` (empty when
        no host registered one). An axis's explicit ``symbol:`` always wins.
    schema_entry : callable, optional
        ``kind -> ReactorSchemaEntry | None`` used to expand short-form sweep
        paths and validate path leaves against registered node schemas.
        Defaults to :func:`boulder.schema_registry.get_schema_entry`. Hosts
        that lazily register their schemas can pass their own accessor.

    Returns
    -------
    list of tuple
        ``[(scenario_id, merged_config_dict), ...]``. Each merged dict is a
        deep copy with the ``scenarios``/``sweep`` directives stripped — the
        id lives only in the tuple, never stamped into the dict itself, since
        ``metadata.scenario_id`` is not a valid config field (see
        :class:`boulder.validation.MetadataModel`) and a merged dict often
        gets written back out and re-validated (e.g. a host dumping one
        scenario's merged config to a temp YAML file before solving it). When
        a ``scenarios:`` mapping is declared, the unmodified base config is
        always the first entry, id :data:`BASELINE_SCENARIO_ID` — otherwise it
        would never be part of the run-set at all (the union below only
        covers the named overlays), so ``Run Sweep`` would silently never
        solve it.
    """
    raw_scenarios = base_raw.get("scenarios")
    if isinstance(raw_scenarios, list):
        raise ValueError(
            "top-level 'scenarios:' as a list ([{id, set, metadata}, ...]) is "
            "no longer supported; migrate to the mapping form — "
            "'scenarios: {<scenario_id>: <overlay-subtree>}'. See "
            "boulder.runset.expand_scenarios."
        )

    base_id = BASELINE_SCENARIO_ID
    scenario_block = raw_scenarios or {}
    global_sweeps = sweeps_of(base_raw)

    if not scenario_block and not global_sweeps:
        return [(base_id, copy.deepcopy(base_raw))]

    if symbols is None:
        symbols = _default_symbols()

    # Strip the directives from the base so downstream consumers never see them.
    base_clean = copy.deepcopy(base_raw)
    base_clean.pop("scenarios", None)
    _strip_run_set_keys(base_clean)

    expanded: List[Tuple[str, dict]] = []

    # 0) The unmodified base config, always first -- named scenarios: overlays
    # only add to the run-set, they never stand in for the base itself.
    if scenario_block:
        expanded.append((BASELINE_SCENARIO_ID, copy.deepcopy(base_clean)))

    # 1) Global sweep points, expanded on the base.
    for sweep_id, patch in (
        _expand_sweep_block(global_sweeps, base_clean, symbols, schema_entry)
        if global_sweeps
        else []
    ):
        sid = f"{base_id}__{sweep_id}" if sweep_id else base_id
        expanded.append((sid, deep_merge(base_clean, patch)))

    # 2) Each scenario overlay; a scenario-local sweep multiplies only itself.
    for key, overlay in scenario_block.items():
        overlay = dict(overlay or {})
        inner_sweeps = sweeps_of(overlay)
        overlay_clean = copy.deepcopy(overlay)
        _strip_run_set_keys(overlay_clean)
        scen_base = deep_merge(base_clean, overlay_clean)
        if inner_sweeps:
            for sweep_id, patch in _expand_sweep_block(
                inner_sweeps, scen_base, symbols, schema_entry
            ):
                sid = f"{key}__{sweep_id}" if sweep_id else key
                expanded.append((sid, deep_merge(scen_base, patch)))
        else:
            expanded.append((key, scen_base))

    return expanded


def _default_symbols() -> Mapping[str, str]:
    """Return the host-registered sweep symbol map (``plugins.sweep_symbols``)."""
    try:
        from .cantera_converter import get_plugins  # noqa: PLC0415

        return get_plugins().sweep_symbols or {}
    except Exception:  # noqa: BLE001 — no plugins available: plain axis names
        return {}


def _axis_label(
    axis_name: str, axis_spec: Mapping[str, Any], symbols: Mapping[str, str]
) -> str:
    """Return an axis's (or chain's) id label: its ``symbol:``, else its first path's leaf."""
    explicit_symbol = axis_spec.get("symbol")
    if explicit_symbol:
        return str(explicit_symbol)
    # A multi-target axis labels itself from its *first* path, so the
    # scenario id stays short and stable no matter how many nodes it drives.
    raw_path = axis_spec.get("path")
    first = (
        raw_path[0] if isinstance(raw_path, (list, tuple)) and raw_path else raw_path
    )
    path = str(first or "")
    leaf = path.rsplit(".", 1)[-1] if path else axis_name
    return symbols.get(leaf) or symbols.get(axis_name) or axis_name


def _expand_sweep_block(
    sweeps_block: dict,
    base_for_paths: dict,
    symbols: Mapping[str, str],
    schema_entry: Optional[Callable[[str], Any]],
) -> List[Tuple[str, dict]]:
    """Cartesian-expand a sweeps block → ``[(sweep_id, patch_dict), ...]``.

    Each axis is ``{path: "<dotted.path>", values: [...]}`` (or ``min``/``max``/
    ``num``); all axes are crossed. ``base_for_paths`` is used only to resolve
    short-form / id-selector paths. Raises ``ValueError`` on a malformed axis.
    """
    from itertools import product  # noqa: PLC0415

    axes = []
    for axis_name, axis_spec in sweeps_block.items():
        raw_path = axis_spec.get("path") if isinstance(axis_spec, dict) else None
        axis_values = (
            sweep_axis_values(axis_spec) if isinstance(axis_spec, dict) else None
        )
        if not raw_path or not axis_values:
            raise ValueError(
                f"sweep.{axis_name} must be a dict with 'path' and either "
                f"'values: [...]' or 'min'/'max'/'num'; got {axis_spec!r}"
            )
        # ``path`` may name several targets, so one swept value can drive
        # parameters that are physically the same quantity but live on
        # different nodes -- e.g. an inlet reservoir's temperature and the
        # isothermal reactor's initial temperature fed by it. Solving those as
        # one axis is the whole point: sweeping only one of them would be
        # physically inconsistent, and a cross-product of the two would mostly
        # produce nonsense combinations.
        raw_paths = (
            list(raw_path) if isinstance(raw_path, (list, tuple)) else [raw_path]
        )
        if not all(isinstance(p, str) and p for p in raw_paths):
            raise ValueError(
                f"sweep.{axis_name}.path must be a dotted string or a list of "
                f"them; got {raw_path!r}"
            )
        axis_paths = tuple(
            _resolve_sweep_path(axis_name, p, base_for_paths, schema_entry)
            for p in raw_paths
        )
        axes.append(
            (_axis_label(axis_name, axis_spec, symbols), axis_paths, list(axis_values))
        )

    points: List[Tuple[str, dict]] = []
    for combo in product(*[a[2] for a in axes]):
        label_parts: List[str] = []
        patch: dict = {}
        # Record each point's axis values under `metadata.sweep_point` as well
        # as writing them into the network. They are the run's *inputs*, and a
        # writer of the collection store turns the numeric ones into scenario
        # attrs -- which is what gives the Scenario pane's Sweep Results plot
        # an X axis without every host having to supply one. Recovering them by
        # parsing the scenario id instead would be fragile.
        sweep_point: dict = {}
        for (label, axis_paths, _), value in zip(axes, combo, strict=True):
            label_parts.append(f"{label}={value}")
            sweep_point[label] = value
            for axis_path in axis_paths:
                _set_dotted(patch, axis_path, value)
        patch.setdefault("metadata", {})["sweep_point"] = sweep_point
        points.append(("__".join(label_parts), patch))
    return points


def sweep_point_of(config: dict) -> Dict[str, Any]:
    """Return a merged scenario config's ``metadata.sweep_point`` axis values.

    Empty for a config that is not a sweep point (a named ``scenarios:``
    overlay, or BASELINE).
    """
    meta = config.get("metadata")
    if not isinstance(meta, dict):
        return {}
    point = meta.get("sweep_point")
    return dict(point) if isinstance(point, dict) else {}


#: Keys on a node/connection dict that are never a scalar property to record.
_ELEMENT_META_KEYS = {"id", "description", "source", "target"}


def _numeric_props(props: dict) -> Dict[str, Any]:
    return {
        k: v
        for k, v in props.items()
        if k not in _ELEMENT_META_KEYS
        and not isinstance(v, bool)
        and isinstance(v, (int, float))
    }


def node_property_attrs(config: dict) -> Dict[str, Any]:
    """Flatten every numeric top-level property of every node/connection.

    Walks the normalized STONE ``nodes:``/``connections:`` lists, emitting
    ``f"in.{id}.{prop}": val`` for every numeric, non-bool leaf. Host-agnostic
    and kind-agnostic — no schema/variable-map registration required — so the
    Sweep Results plot's axis picker can offer every node's declared inputs
    without a host having to enumerate them one at a time via
    :attr:`~boulder.cantera_converter.BoulderPlugins.scenario_attrs`.

    Handles both element shapes a STONE config may use: the type-keyed style
    (``{id, TypeName: {prop: val, ...}}``) and the legacy explicit
    ``properties:`` sub-dict style. Nested dicts/lists (e.g. per-layer
    insulation properties) are skipped: there's no natural single scalar to
    record for them.
    """
    attrs: Dict[str, Any] = {}
    for key in ("nodes", "connections"):
        for element in config.get(key) or []:
            if not isinstance(element, dict):
                continue
            eid = element.get("id")
            if not eid:
                continue
            if "properties" in element and isinstance(element["properties"], dict):
                for prop, value in _numeric_props(element["properties"]).items():
                    attrs[f"in.{eid}.{prop}"] = value
                continue
            for type_key, props in element.items():
                if type_key in _ELEMENT_META_KEYS or not isinstance(props, dict):
                    continue
                for prop, value in _numeric_props(props).items():
                    attrs[f"in.{eid}.{prop}"] = value
    return attrs


def _resolve_sweep_path(
    axis_name: str,
    axis_path: str,
    base_config: dict,
    schema_entry: Optional[Callable[[str], Any]] = None,
) -> str:
    """Expand short-form sweep paths and validate against registered schemas.

    Behaviour:

    * If *axis_path* starts with ``nodes[`` we trust it and only validate the
      target field exists on the node's registered schema (if any).
    * Otherwise it is treated as a short-form property key.  The YAML is
      scanned for nodes whose kind is registered in the schema registry and
      whose schema declares the key.  When exactly one node matches, the path
      is expanded to ``nodes[id=<that-id>].properties.<key>``.  Ambiguity or
      absence raises :class:`ValueError` with the full list of candidates, so
      users can pick a specific node explicitly.
    """
    if schema_entry is None:
        try:
            from .schema_registry import get_schema_entry  # noqa: PLC0415

            schema_entry = get_schema_entry
        except ImportError:
            return axis_path

    if axis_path.startswith("nodes["):
        _validate_sweep_path_leaf(axis_name, axis_path, base_config, schema_entry)
        return axis_path

    if axis_path.startswith("network["):
        # STONE v2: network[id=<X>].<KindKey>.<field> — trusted as-is.
        return axis_path

    if "." in axis_path:
        return axis_path  # non-node dotted paths (metadata, phases, ...) are OK

    key = axis_path
    candidates: List[str] = []
    # Check both internal (nodes) and STONE v2 (network) item lists.
    items = list(base_config.get("nodes") or []) + list(
        base_config.get("network") or []
    )
    for node in items:
        kind = node.get("type")
        if not kind:
            continue
        entry = schema_entry(kind)
        if entry is None or entry.schema is None:
            continue
        fields = getattr(entry.schema, "model_fields", None) or {}
        if key in fields:
            candidates.append(node.get("id"))

    if len(candidates) == 1:
        return f"nodes[id={candidates[0]}].properties.{key}"
    if len(candidates) > 1:
        raise ValueError(
            f"sweeps.{axis_name}.path={axis_path!r} is ambiguous: matches "
            f"nodes {candidates}. Qualify the path explicitly, e.g. "
            f"nodes[id={candidates[0]}].properties.{key}."
        )
    raise ValueError(
        f"sweeps.{axis_name}.path={axis_path!r} matches no registered "
        "reactor field. Either pass a full dotted path (metadata.*, phases.*, "
        "nodes[id=...]... or network[id=...]...) or register a schema that declares this field."
    )


def _validate_sweep_path_leaf(
    axis_name: str,
    axis_path: str,
    base_config: dict,
    schema_entry: Callable[[str], Any],
) -> None:
    """Best-effort leaf validation for ``nodes[id=...].properties.FIELD`` paths."""
    import re  # noqa: PLC0415

    match = re.match(
        r"^nodes\[id=(?P<nid>[^\]]+)\]\.properties\.(?P<leaf>[^.]+)$",
        axis_path,
    )
    if not match:
        return
    nid = match.group("nid")
    leaf = match.group("leaf")
    target = next(
        (n for n in base_config.get("nodes") or [] if n.get("id") == nid), None
    )
    if target is None:
        raise ValueError(f"sweeps.{axis_name}: node id {nid!r} not found in config.")
    kind = target.get("type")
    if not kind:
        return
    entry = schema_entry(kind)
    if entry is None or entry.schema is None:
        return
    fields = getattr(entry.schema, "model_fields", None) or {}
    if leaf not in fields:
        raise ValueError(
            f"sweeps.{axis_name}: node {nid!r} (kind {kind!r}) has no "
            f"schema field {leaf!r}. Known fields: {sorted(fields)}."
        )


def _set_dotted(target: dict, dotted_path: str, value: Any) -> None:
    """Set *value* at *dotted_path* inside *target*.

    Supports two segment forms:

    * Plain keys: ``metadata.scenario_id``.
    * Id-keyed list selection: ``nodes[id=torch].properties.T_out`` — the
      current node is expected to be a list of dicts; the segment looks up
      (or appends) the element with matching ``id`` field.  This mirrors
      the id-based list merging behavior of :func:`deep_merge`.

    Intermediate dicts / list elements are created as needed.
    """
    import re  # noqa: PLC0415

    segments = dotted_path.split(".")
    bracket_re = re.compile(r"^([^\[]+)\[([^=\]]+)=([^\]]+)\]$")

    cur: Any = target
    for i, seg in enumerate(segments):
        is_last = i == len(segments) - 1
        m = bracket_re.match(seg)
        if m:
            list_key, match_key, match_val = m.group(1), m.group(2), m.group(3)
            if list_key not in cur or not isinstance(cur[list_key], list):
                cur[list_key] = []
            lst = cur[list_key]
            found = None
            for item in lst:
                if isinstance(item, dict) and str(item.get(match_key)) == match_val:
                    found = item
                    break
            if found is None:
                found = {match_key: match_val}
                lst.append(found)
            if is_last:
                raise ValueError(
                    f"Cannot set value at list-selector segment {seg!r}; "
                    "end the path with a plain key after the selector."
                )
            cur = found
        else:
            if is_last:
                cur[seg] = value
                return
            nxt = cur.get(seg) if isinstance(cur, dict) else None
            if not isinstance(nxt, dict):
                nxt = {}
                cur[seg] = nxt
            cur = nxt


def _get_dotted(source: Any, dotted_path: str) -> Any:
    """Read the value at *dotted_path* (the :func:`_set_dotted` grammar); ``None`` if absent."""
    bracket_re = re.compile(r"^([^\[]+)\[([^=\]]+)=([^\]]+)\]$")
    cur: Any = source
    for seg in dotted_path.split("."):
        m = bracket_re.match(seg)
        if m:
            list_key, match_key, match_val = m.group(1), m.group(2), m.group(3)
            lst = cur.get(list_key) if isinstance(cur, dict) else None
            cur = next(
                (
                    item
                    for item in (lst or [])
                    if isinstance(item, dict) and str(item.get(match_key)) == match_val
                ),
                None,
            )
        else:
            cur = cur.get(seg) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


# ---------------------------------------------------------------------------
# Sequential run-sets: ``scenarios_sweep.for`` / ``scenarios_sweep.while``.
# ---------------------------------------------------------------------------
#
# A grid axis enumerates independent points up front. A chain cannot: each of
# its points may depend on the previous solve -- its converged state seeds the
# next point (``initial: from_previous``, the warm start upstream's loops rely
# on when they keep solving the same live ReactorNet), and a ``while:``
# condition is read from it. So a chain is *iterated*, not expanded: the solve
# loop records each step's final reactor states in a :class:`RunSetCursor` and
# :func:`iter_run_set` builds the next point from them.

#: ``initial:`` values a chain accepts -- where each step's starting state comes from.
INITIAL_FROM_CONFIG = "from_config"
INITIAL_FROM_PREVIOUS = "from_previous"

_CONDITION_OPS: Dict[str, Callable[[float, float], bool]] = {
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
}
_UPDATE_MODES: Tuple[str, ...] = ("multiply", "add", "set")
#: Node kinds that are boundary conditions, never seeded by a warm start.
_BOUNDARY_KINDS = frozenset({"Reservoir", "OutletSink"})
#: Keys on a node item that are not its kind key.
_NODE_META_KEYS = frozenset({"id", "description", "mechanism", "source", "target"})
_RESULT_PATH_RE = re.compile(r"^[A-Za-z_]\w*\[id=(?P<id>[^\]]+)\]\.(?P<attr>.+)$")


@dataclass(frozen=True)
class SequentialSpec:
    """A validated ``for:``/``while:`` chain -- see :func:`sequential_of`."""

    kind: str
    label: str
    paths: Tuple[str, ...]
    values: Tuple[Any, ...] = ()
    condition: Optional[Tuple[str, str, float]] = None
    update: Optional[Tuple[str, float]] = None
    max_iters: int = 200
    from_previous: bool = False


class RunSetCursor:
    """Hand-off from the solve loop back into :func:`iter_run_set`.

    ``previous_states`` is ``{reactor_id: {"T": K, "P": Pa, "X": {species:
    mole_fraction}, "Y": {...}}}`` for the last point the loop finished -- solved
    fresh (``boulder.sweep_runner.final_states_of``) or read back from a cached
    store entry. The loop must set it before pulling the next point; the
    iterator never reads results itself.
    """

    def __init__(self) -> None:
        self.previous_states: Optional[Dict[str, Dict[str, Any]]] = None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_float(value: Any) -> float:
    """Read a number from a YAML scalar, unit-bearing strings (``"0.1 s"``) included."""
    if _is_number(value):
        return float(value)
    if isinstance(value, str):
        from .utils import coerce_unit_string  # noqa: PLC0415

        coerced = coerce_unit_string(value)
        if _is_number(coerced):
            return float(coerced)
        return float(value.strip().split()[0])
    raise ValueError(f"cannot read a number from {value!r}")


def sequential_block_of(block: dict) -> Optional[Tuple[str, dict]]:
    """Return ``(kind, spec_dict)`` for a block's ``for:``/``while:``, else ``None``.

    Cheap and non-validating (for availability endpoints); raises only when
    both are declared, which has no meaning. :func:`sequential_of` validates.
    """
    rs = run_set_block(block)
    present = [k for k in SEQUENTIAL_KINDS if k in rs]
    if len(present) > 1:
        raise ValueError(f"{RUN_SET_KEY}: declare either 'for:' or 'while:', not both")
    if not present:
        return None
    spec = rs[present[0]]
    if not isinstance(spec, dict):
        raise ValueError(f"{RUN_SET_KEY}.{present[0]} must be a mapping; got {spec!r}")
    return present[0], spec


def sequential_of(
    raw: dict,
    *,
    symbols: Optional[Mapping[str, str]] = None,
    schema_entry: Optional[Callable[[str], Any]] = None,
) -> Optional[SequentialSpec]:
    """Validate a config's ``scenarios_sweep.for`` / ``.while`` chain.

    ``for:`` -- ``parameter`` (a path, or a list of paths one value drives
    together, same syntax as a grid axis) and the values to walk in order
    (``values:`` or ``min``/``max``/``num``). ``while:`` -- ``parameter``, a
    ``condition: {path, gt|ge|lt|le: number}`` read from the previous step's
    result, an ``update: {multiply|add|set: number}`` applied after each step,
    and a ``max_iters`` safety cap. Both take ``initial: from_config`` (the
    default -- every step starts from the network as written) or ``initial:
    from_previous`` (each step is seeded with the previous step's converged
    reactor states -- a warm start; the swept ``parameter`` still wins). A chain
    cannot share its block with grid axes: the run-set is one or the other.

    Returns ``None`` when the config declares no chain; raises ``ValueError``
    on a malformed one.
    """
    found = sequential_block_of(raw)
    if found is None:
        return None
    kind, spec = found
    where = f"{RUN_SET_KEY}.{kind}"
    if sweeps_of(raw):
        raise ValueError(
            f"{where}: a chain cannot sit alongside grid axes in one block"
        )

    raw_paths = spec.get("parameter")
    candidates = (
        list(raw_paths) if isinstance(raw_paths, (list, tuple)) else [raw_paths]
    )
    if not raw_paths or not all(isinstance(p, str) and p for p in candidates):
        raise ValueError(
            f"{where}.parameter must be a dotted path or a list of them; got {raw_paths!r}"
        )
    paths_list: List[str] = [str(p) for p in candidates]
    if symbols is None:
        symbols = _default_symbols()
    paths = tuple(_resolve_sweep_path(kind, p, raw, schema_entry) for p in paths_list)
    # A chain has no axis name to label its points with, so the label is the
    # parameter's path leaf (``tau_s``, ``temperature``) -- through the host
    # symbol map like an axis leaf -- unless an explicit ``symbol:`` is given.
    leaf = str(paths_list[0]).rsplit(".", 1)[-1]
    label = str(spec.get("symbol") or symbols.get(leaf) or leaf)

    initial = spec.get("initial", INITIAL_FROM_CONFIG)
    if initial not in (INITIAL_FROM_CONFIG, INITIAL_FROM_PREVIOUS):
        raise ValueError(
            f"{where}.initial must be '{INITIAL_FROM_CONFIG}' or "
            f"'{INITIAL_FROM_PREVIOUS}'; got {initial!r}"
        )
    from_previous = initial == INITIAL_FROM_PREVIOUS

    if kind == "for":
        values = sweep_axis_values(spec)
        if not values:
            raise ValueError(f"{where} needs 'values: [...]' or 'min'/'max'/'num'")
        return SequentialSpec(
            kind,
            label,
            paths,
            values=tuple(values),
            max_iters=len(values),
            from_previous=from_previous,
        )

    max_iters = spec.get("max_iters", 200)
    if not isinstance(max_iters, int) or isinstance(max_iters, bool) or max_iters < 1:
        raise ValueError(
            f"{where}.max_iters must be a positive integer; got {max_iters!r}"
        )
    condition = spec.get("condition")
    if not isinstance(condition, dict) or not isinstance(condition.get("path"), str):
        raise ValueError(
            f"{where}.condition must be {{path: <result path>, gt|ge|lt|le: <number>}}; "
            f"got {condition!r}"
        )
    ops = [op for op in _CONDITION_OPS if op in condition]
    if len(ops) != 1 or not _is_number(condition[ops[0]]):
        raise ValueError(
            f"{where}.condition needs exactly one of gt/ge/lt/le with a numeric bound; "
            f"got {condition!r}"
        )
    update = spec.get("update")
    if not isinstance(update, dict):
        raise ValueError(
            f"{where}.update must be {{multiply|add|set: <number>}}; got {update!r}"
        )
    modes = [m for m in _UPDATE_MODES if m in update]
    if len(modes) != 1 or not _is_number(update[modes[0]]):
        raise ValueError(
            f"{where}.update needs exactly one of multiply/add/set with a numeric operand; "
            f"got {update!r}"
        )
    return SequentialSpec(
        kind,
        label,
        paths,
        condition=(str(condition["path"]), ops[0], float(condition[ops[0]])),
        update=(modes[0], float(update[modes[0]])),
        max_iters=max_iters,
        from_previous=from_previous,
    )


def sequential_start_value(spec: SequentialSpec, base_raw: dict) -> float:
    """Return a ``while:`` chain's first value: the parameter as written in the config."""
    current = _get_dotted(base_raw, spec.paths[0])
    if current is None:
        raise ValueError(
            f"{RUN_SET_KEY}.while: parameter {spec.paths[0]!r} is not set in the "
            "config, so the chain has no starting value"
        )
    return _as_float(current)


def next_sequential_value(spec: SequentialSpec, current: float) -> float:
    """Apply a ``while:`` chain's ``update`` to *current* (rounded for clean ids)."""
    if spec.update is None:
        raise ValueError(f"{RUN_SET_KEY}.{spec.kind} has no update rule")
    mode, operand = spec.update
    if mode == "multiply":
        nxt = current * operand
    elif mode == "add":
        nxt = current + operand
    else:
        nxt = operand
    return round(nxt, 10)


def result_value_at(states: Mapping[str, Mapping[str, Any]], path: str) -> float:
    """Read ``network[id=<reactor>].T`` / ``.P`` / ``.X.<species>`` from *states*."""
    m = _RESULT_PATH_RE.match(path)
    if m is None:
        raise ValueError(
            f"result path {path!r} must look like network[id=<reactor>].T "
            "(or .P, .X.<species>, .Y.<species>)"
        )
    rid, attr = m.group("id"), m.group("attr")
    state = states.get(rid)
    if state is None:
        raise ValueError(
            f"result path {path!r}: no reactor {rid!r} in the previous step's "
            f"results (have {sorted(states)})"
        )
    if attr in ("T", "P"):
        return float(state[attr])
    if attr[:2] in ("X.", "Y."):
        fractions = state.get(attr[0]) or {}
        species = attr[2:]
        if species not in fractions:
            raise ValueError(
                f"result path {path!r}: species {species!r} not in reactor {rid!r}'s composition"
            )
        return float(fractions[species])
    raise ValueError(
        f"result path {path!r}: unknown attribute {attr!r}; use T, P, X.<species> or Y.<species>"
    )


def condition_holds(
    spec: SequentialSpec, previous_states: Optional[Mapping[str, Mapping[str, Any]]]
) -> bool:
    """Evaluate a ``while:`` condition against the previous step's reactor states."""
    if spec.condition is None:
        raise ValueError(f"{RUN_SET_KEY}.{spec.kind} has no condition")
    path, op, bound = spec.condition
    if not previous_states:
        raise ValueError(
            f"{RUN_SET_KEY}.while: the previous step produced no reactor state to "
            f"evaluate {path!r} against"
        )
    return _CONDITION_OPS[op](result_value_at(previous_states, path), bound)


def _iter_node_items(config: dict) -> Iterator[dict]:
    """Yield every node item of a STONE v2 config (``network:`` or stage blocks)."""
    blocks: List[Any] = [config.get("network")]
    stages = config.get("stages")
    if isinstance(stages, dict):
        blocks.extend(config.get(sid) for sid in stages)
    for block in blocks:
        if not isinstance(block, list):
            continue
        for item in block:
            if isinstance(item, dict) and "source" not in item and "target" not in item:
                yield item


def _composition_string(fractions: Mapping[str, Any]) -> str:
    return ",".join(
        f"{sp}:{float(x):.6g}" for sp, x in fractions.items() if float(x) > 0.0
    )


def apply_previous_state(
    config: dict, previous_states: Mapping[str, Mapping[str, Any]]
) -> List[str]:
    """Seed every non-boundary reactor's ``initial:`` from *previous_states*, in place.

    The warm start behind ``initial: from_previous``: each reactor whose id has
    a converged state gets that state's temperature, pressure and composition
    as its ``initial:`` block -- what continuing an already-solved
    ``ReactorNet`` does. Reservoirs and outlet sinks are boundary conditions and
    are never touched. Pressure is only seeded where the node has no top-level
    ``pressure:`` (a const-pressure reactor's operating constraint). Returns the
    ids seeded. Callers apply the chain's own ``parameter`` *after* this, so
    the swept value always wins over the carried one.
    """
    seeded: List[str] = []
    for node in _iter_node_items(config):
        nid = node.get("id")
        state = previous_states.get(str(nid)) if nid else None
        if not state:
            continue
        kind = next((k for k in node if k not in _NODE_META_KEYS), None)
        if kind is None or kind in _BOUNDARY_KINDS:
            continue
        props = node.get(kind)
        if not isinstance(props, dict):
            props = {}
            node[kind] = props
        initial = props.get("initial")
        if not isinstance(initial, dict):
            initial = {}
            props["initial"] = initial
        if state.get("T") is not None:
            initial["temperature"] = float(state["T"])
        if state.get("P") is not None and "pressure" not in props:
            initial["pressure"] = float(state["P"])
        composition = _composition_string(state.get("X") or {})
        if composition:
            initial["composition"] = composition
            initial.pop("mass_composition", None)
        seeded.append(str(nid))
    return seeded


def sequential_point(
    spec: SequentialSpec,
    base_clean: dict,
    value: Any,
    previous_states: Optional[Mapping[str, Mapping[str, Any]]],
) -> Tuple[str, dict]:
    """Build one chain point: carry the previous state (if any), then set the parameter.

    Ids follow the grid convention (``BASELINE__<label>=<value>``) and the value
    is recorded under ``metadata.sweep_point`` like an axis value, so the Sweep
    Results plot gets its X axis the same way.
    """
    cfg = copy.deepcopy(base_clean)
    if spec.from_previous and previous_states:
        apply_previous_state(cfg, previous_states)
    patch: dict = {}
    for path in spec.paths:
        _set_dotted(patch, path, value)
    patch.setdefault("metadata", {})["sweep_point"] = {spec.label: value}
    return f"{BASELINE_SCENARIO_ID}__{spec.label}={value}", deep_merge(cfg, patch)


def iter_run_set(
    raw: dict,
    cursor: RunSetCursor,
    *,
    symbols: Optional[Mapping[str, str]] = None,
    schema_entry: Optional[Callable[[str], Any]] = None,
) -> Iterator[Tuple[str, dict]]:
    """Yield the run-set's ``(scenario_id, merged_config)`` points, lazily.

    The eager part (``scenarios:`` overlays and grid axes) comes straight from
    :func:`expand_scenarios`; a ``for:``/``while:`` chain follows, one point at a
    time, because each may depend on the previous solve -- the loop consuming
    this iterator must record every step's final reactor states in *cursor*
    before asking for the next point.

    The first ``while:`` point is the config as written, so it is always
    solved; the condition is checked before every *later* point, on the
    previous result -- like a Python ``while`` re-testing after each iteration,
    so the point that trips it (the extinguished combustor) is recorded too.
    A chain declared without ``scenarios:`` yields only its own points (no
    separate ``BASELINE`` entry: its first point *is* the base config).
    """
    spec = sequential_of(raw, symbols=symbols, schema_entry=schema_entry)
    if spec is None or raw.get("scenarios"):
        yield from expand_scenarios(raw, symbols=symbols, schema_entry=schema_entry)
    if spec is None:
        return
    base_clean = copy.deepcopy(raw)
    base_clean.pop("scenarios", None)
    _strip_run_set_keys(base_clean)

    if spec.kind == "for":
        for value in spec.values:
            previous = cursor.previous_states if spec.from_previous else None
            yield sequential_point(spec, base_clean, value, previous)
        return

    value = sequential_start_value(spec, base_clean)
    for step in range(spec.max_iters):
        if step:
            if not condition_holds(spec, cursor.previous_states):
                return
            value = next_sequential_value(spec, value)
        previous = cursor.previous_states if spec.from_previous else None
        yield sequential_point(spec, base_clean, value, previous)
