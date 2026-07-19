"""STONE run-set primitives: inline ``scenario:`` / ``sweep:`` expansion.

A STONE YAML may declare parameter variations inline (STONE_SPECIFICATIONS.md,
Section 14), avoiding a glob of overlay files:

``scenario:``
    Mapping ``{id: overlay-subtree}``. Each value is a STONE subtree
    (``metadata``/``settings``/``network``/…) deep-merged onto the base via
    :func:`deep_merge` (which supports id-keyed ``nodes``/``connections``
    merging) — exactly the overlay a standalone ``from:`` file carries. The
    mapping **key is the scenario id**.

``sweep:`` (or ``sweeps:``)
    Mapping axis name → ``{path, values | min/max/num}``, crossed as a
    Cartesian product. May appear at the top level (expanded on the base) or
    *inside* a ``scenario:`` entry (expanded on that scenario only).

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
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Deep merge with id-keyed list support (the STONE overlay merge).
# ---------------------------------------------------------------------------


def _is_id_based_list(lst: list) -> bool:
    """Return whether *lst* is a non-empty list of dicts that all carry ``id``."""
    return bool(lst) and all(
        isinstance(item, dict) and "id" in item for item in lst
    )


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

    The ``scenario:`` directive is **not inherited**: a named scenario mapping
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
    base.pop("scenario", None)  # the named run-set is not inherited (sweeps are)
    return deep_merge(base, overlay)


# ---------------------------------------------------------------------------
# Sweep-axis primitives.
# ---------------------------------------------------------------------------


def sweeps_of(block: dict) -> dict:
    """Return the sweep block of a config/overlay, accepting ``sweep:`` or ``sweeps:``."""
    return block.get("sweeps") or block.get("sweep") or {}


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
    """Return the union run-set size of a config's ``scenario:``/``sweep:`` blocks.

    Global sweep points ⊎ each ``scenario:`` entry (its inner sweep, else 1) —
    the same union semantics :func:`expand_scenarios` implements, computed
    without deep-merging or resolving sweep paths (cheap enough for an
    availability endpoint).
    """
    scenario = raw.get("scenario") or {}
    total = _sweep_size(sweeps_of(raw))
    for overlay in scenario.values():
        inner = sweeps_of(overlay or {})
        total += _sweep_size(inner) if inner else 1
    return total


def resolve_store_path(
    raw: Dict[str, Any], config_path: "Optional[str | Path]"
) -> Optional[Path]:
    """Return the collection store a run-set writes to, or ``None``.

    Declared via ``metadata.extra.scenario_store`` (resolved relative to the
    config), else the ``<config-stem>_scenarios.h5`` default next to the
    config. ``None`` when *config_path* is unset — there is no config to
    resolve a default against.
    """
    if not config_path:
        return None
    cfg = Path(config_path).resolve()
    rel = ((raw.get("metadata") or {}).get("extra") or {}).get("scenario_store")
    if rel:
        p = Path(rel)
        return p if p.is_absolute() else cfg.parent / p
    return cfg.parent / f"{cfg.stem}_scenarios.h5"


# ---------------------------------------------------------------------------
# Run-set expansion.
# ---------------------------------------------------------------------------


def expand_scenarios(
    base_raw: dict,
    *,
    symbols: Optional[Mapping[str, str]] = None,
    schema_entry: Optional[Callable[[str], Any]] = None,
) -> List[Tuple[str, dict]]:
    """Expand a STONE YAML's inline ``scenario:`` / ``sweep:`` blocks.

    **Union semantics** (not a global cross-product): the run set is the
    base's global-sweep points **⊎** each ``scenario:`` entry (each expanded
    across its *own* inner sweep if it declares one). A top-level sweep and
    the scenarios do not cross-multiply.

    When neither block is present, returns a single ``(scenario_id, base)``
    tuple using ``metadata.scenario_id`` or ``"BASE"``.

    Parameters
    ----------
    base_raw : dict
        The raw (``from:``-resolved) config. Not mutated.
    symbols : Mapping[str, str], optional
        Axis-name/path-leaf → symbol mapping used to label sweep points in
        scenario ids (e.g. ``diameter`` → ``TF_D`` gives ``BASE__TF_D=0.03``).
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
        deep copy with the ``scenario``/``sweep`` directives stripped, and
        ``metadata.scenario_id`` set to the scenario id.
    """
    if "scenarios" in base_raw:
        raise ValueError(
            "top-level 'scenarios:' (list of {id, set, metadata}) is no longer "
            "supported; migrate to the 'scenario:' mapping form — "
            "'scenario: {<scenario_id>: <overlay-subtree>}'. See "
            "boulder.runset.expand_scenarios."
        )

    base_meta = base_raw.get("metadata") or {}
    base_id = base_meta.get("scenario_id", "BASE")
    scenario_block = base_raw.get("scenario") or {}
    global_sweeps = sweeps_of(base_raw)

    if not scenario_block and not global_sweeps:
        return [(base_id, copy.deepcopy(base_raw))]

    if symbols is None:
        symbols = _default_symbols()

    # Strip the directives from the base so downstream consumers never see them.
    base_clean = copy.deepcopy(base_raw)
    for key in ("scenario", "sweep", "sweeps"):
        base_clean.pop(key, None)

    expanded: List[Tuple[str, dict]] = []

    def _with_id(cfg: dict, sid: str) -> dict:
        return deep_merge(cfg, {"metadata": {"scenario_id": sid}})

    # 1) Global sweep points, expanded on the base.
    for sweep_id, patch in (
        _expand_sweep_block(global_sweeps, base_clean, symbols, schema_entry)
        if global_sweeps
        else []
    ):
        sid = f"{base_id}__{sweep_id}" if sweep_id else base_id
        expanded.append((sid, _with_id(deep_merge(base_clean, patch), sid)))

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
                expanded.append((sid, _with_id(deep_merge(scen_base, patch), sid)))
        else:
            expanded.append((key, _with_id(scen_base, key)))

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
        path = str(axis_spec.get("path", ""))
        leaf = path.rsplit(".", 1)[-1] if path else axis_name
        return symbols.get(leaf) or symbols.get(axis_name) or axis_name

    axes = []
    for axis_name, axis_spec in sweeps_block.items():
        axis_path = axis_spec.get("path") if isinstance(axis_spec, dict) else None
        axis_values = (
            sweep_axis_values(axis_spec) if isinstance(axis_spec, dict) else None
        )
        if not axis_path or not axis_values:
            raise ValueError(
                f"sweep.{axis_name} must be a dict with 'path' and either "
                f"'values: [...]' or 'min'/'max'/'num'; got {axis_spec!r}"
            )
        axis_path = _resolve_sweep_path(
            axis_name, axis_path, base_for_paths, schema_entry
        )
        axes.append((_axis_label(axis_name, axis_spec), axis_path, list(axis_values)))

    points: List[Tuple[str, dict]] = []
    for combo in product(*[a[2] for a in axes]):
        label_parts: List[str] = []
        patch: dict = {}
        for (label, axis_path, _), value in zip(axes, combo, strict=True):
            label_parts.append(f"{label}={value}")
            _set_dotted(patch, axis_path, value)
        points.append(("__".join(label_parts), patch))
    return points


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
