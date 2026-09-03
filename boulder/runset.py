"""STONE run-set primitives: inline ``scenarios:`` / ``sweep:`` expansion.

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

``sweep:`` (or ``sweeps:``)
    Mapping axis name → ``{path, values | min/max/num}``, crossed as a
    Cartesian product. May appear at the top level (expanded on the base) or
    *inside* a ``scenarios:`` entry (expanded on that scenario only).

This module is the reference implementation of those semantics: the Run Sweep
API sizes run-sets with :func:`run_set_size`, and the generic
:mod:`boulder.sweep_runner` expands them with :func:`expand_scenarios`. Host
packages should call these functions rather than re-implementing the rules.

Everything here is pure config manipulation — no solving, no I/O beyond
:func:`load_yaml_with_inheritance` — and host-agnostic: host-specific naming
(axis-label symbols) and schema knowledge enter only through the
``plugins.sweep_symbols`` registry and the ``schema_entry`` hook.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

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


def load_yaml_with_inheritance(path: "str | Path") -> dict:
    """Load a STONE YAML with optional ``from:`` inheritance.

    If a top-level ``from`` key is present, that file is loaded first
    (recursively) and deep-merged with the current file content (excluding
    ``from``). Relative ``from`` paths are resolved against the current file
    directory.

    The ``scenarios:`` directive is **not inherited**: a named scenario mapping
    declares *this* file's run-set, so a parent's scenarios must not leak into
    a child (which would re-run them against the child's base). ``sweep:`` /
    ``sweeps:`` **are** inherited — a child overlay legitimately re-runs the
    parent's parameter sweep with overrides (e.g. a different mechanism).
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
    base = load_yaml_with_inheritance(parent_path)
    base.pop("scenarios", None)  # the named run-set is not inherited (sweeps are)
    return deep_merge(base, overlay)


# ---------------------------------------------------------------------------
# Sweep-axis primitives.
# ---------------------------------------------------------------------------


#: Keys inside a ``sweep:``/``sweeps:`` block that configure the run-set rather
#: than declare an axis. Filtered out of every axis-iterating code path.
SWEEP_RESERVED_KEYS = frozenset({"runner"})


def sweeps_of(block: dict) -> dict:
    """Return a config/overlay's sweep **axes**, accepting ``sweep:`` or ``sweeps:``.

    Reserved keys (:data:`SWEEP_RESERVED_KEYS`) are stripped, so every caller
    that treats the result as ``{axis_name: axis_spec}`` stays correct as
    non-axis configuration is added to the block.
    """
    raw = block.get("sweeps") or block.get("sweep") or {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k not in SWEEP_RESERVED_KEYS}


def sweep_runner_of(block: dict) -> Optional[str]:
    """Return a config's declared host sweep runner, or ``None``.

    ``sweep.runner`` is a dotted ``"package.module:callable"`` reference to a
    host function that produces the run-set itself, for run-sets that no
    declarative axis can express — a sweep whose points must be solved
    *sequentially* (each warm-started from the last, e.g. tracing a combustor's
    extinction branch), or whose length is not known in advance.

    Declaring it in the config is deliberate: Boulder used to *guess*, running
    any file literally named ``run_sweep.py`` sitting next to the config. That
    coupled behaviour to a filename, was invisible in the config, and silently
    stopped working when Run Sweep moved in-process. An explicit dotted path is
    resolvable, greppable, and testable.
    """
    raw = block.get("sweeps") or block.get("sweep") or {}
    if not isinstance(raw, dict):
        return None
    runner = raw.get("runner")
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
    """Return the union run-set size of a config's ``scenarios:``/``sweep:`` blocks.

    The unmodified base config (:data:`BASELINE_SCENARIO_ID`) ⊎ global sweep
    points ⊎ each ``scenarios:`` entry (its inner sweep, else 1) — the same
    union semantics :func:`expand_scenarios` implements, computed without
    deep-merging or resolving sweep paths (cheap enough for an availability
    endpoint).
    """
    scenarios = raw.get("scenarios") or {}
    scenarios = scenarios if isinstance(scenarios, dict) else {}
    total = 1 if scenarios else 0
    total += _sweep_size(sweeps_of(raw))
    for overlay in scenarios.values():
        inner = sweeps_of(overlay or {})
        total += _sweep_size(inner) if inner else 1
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
    tuple using :data:`BASELINE_SCENARIO_ID`.

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
    for key in ("scenarios", "sweep", "sweeps"):
        base_clean.pop(key, None)

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
        overlay_clean.pop("sweep", None)
        overlay_clean.pop("sweeps", None)
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

    def _axis_label(axis_name: str, axis_spec: Dict[str, Any]) -> str:
        explicit_symbol = axis_spec.get("symbol")
        if explicit_symbol:
            return str(explicit_symbol)
        # A multi-target axis labels itself from its *first* path, so the
        # scenario id stays short and stable no matter how many nodes it drives.
        raw_path = axis_spec.get("path")
        first = (
            raw_path[0]
            if isinstance(raw_path, (list, tuple)) and raw_path
            else raw_path
        )
        path = str(first or "")
        leaf = path.rsplit(".", 1)[-1] if path else axis_name
        return symbols.get(leaf) or symbols.get(axis_name) or axis_name

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
        axes.append((_axis_label(axis_name, axis_spec), axis_paths, list(axis_values)))

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
