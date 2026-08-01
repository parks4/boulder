"""Scenario authoring: create/update/delete a named ``scenarios:`` overlay on disk.

Complements :mod:`boulder.api.routes.scenarios` (which only *reads* precomputed
trajectories from the HDF5 scenario store) with the input side of the Scenario
Pane: creating a new scenario adds a new named overlay, editing it changes
only that overlay's subtree, and ``Run Sweep`` is what turns overlays into
trajectories.

Every function here mutates only the targeted ``scenarios.<id>`` subtree of the
YAML on disk via ``ruamel.yaml`` — nodes, connections, settings, and comments
elsewhere in the file are left untouched.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .config import (
    _CONN_STANDARD_FIELDS,
    _NODE_STANDARD_FIELDS,
    get_yaml_with_comments,
    load_config_file_with_comments,
    load_yaml_string_with_comments,
    yaml_to_string_with_comments,
)
from .runset import BASELINE_SCENARIO_ID

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: Scenario ids a user cannot author — reserved for a synthesized run-set
#: entry (see boulder.runset.expand_scenarios). A user-declared "scenarios:"
#: entry with a reserved id would otherwise collide with that synthesized one.
_RESERVED_SCENARIO_IDS = frozenset({BASELINE_SCENARIO_ID})


class ScenarioEditError(ValueError):
    """Invalid scenario id / body / operation — routes map this to HTTP 4xx."""


def _validate_id(scenario_id: str) -> None:
    if not scenario_id or not _ID_RE.match(scenario_id):
        raise ScenarioEditError(
            f"Invalid scenario id {scenario_id!r}: use letters, digits, '_' or '-' only"
        )
    if scenario_id in _RESERVED_SCENARIO_IDS:
        raise ScenarioEditError(
            f"Scenario id {scenario_id!r} is reserved (the unmodified base "
            "config's own run-set entry) and cannot be used for an authored scenario"
        )


def _load(cfg_path: Path) -> CommentedMap:
    data = load_config_file_with_comments(str(cfg_path))
    if not isinstance(data, CommentedMap):
        raise ScenarioEditError(f"{cfg_path} does not contain a YAML mapping")
    return data


def _save(cfg_path: Path, data: CommentedMap) -> None:
    yaml_obj = get_yaml_with_comments()
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml_obj.dump(data, f)


def _overlay_yaml_text(overlay: Any) -> str:
    return yaml_to_string_with_comments(
        overlay if overlay is not None else CommentedMap()
    )


def list_scenario_ids(cfg_path: Path) -> List[str]:
    """Return the run-set's scenario ids, in run-set order.

    The unmodified base config's own synthesized entry
    (:data:`~boulder.runset.BASELINE_SCENARIO_ID`) is prepended whenever the
    ``scenarios:`` mapping is non-empty — matching
    :func:`boulder.runset.expand_scenarios`, which always solves it first —
    so it's listed (and clonable, see :func:`create_scenario`) even before
    the first Run Sweep.
    """
    data = _load(cfg_path)
    scenario_map = data.get("scenarios") or {}
    ids = list(scenario_map.keys())
    if ids:
        ids.insert(0, BASELINE_SCENARIO_ID)
    return ids


def create_scenario(
    cfg_path: Path, scenario_id: str, base_scenario_id: Optional[str] = None
) -> str:
    """Add a new (blank or cloned) scenario overlay. Returns its YAML text."""
    _validate_id(scenario_id)
    data = _load(cfg_path)
    scenario_map = data.get("scenarios")
    if scenario_map is None:
        scenario_map = CommentedMap()
        data["scenarios"] = scenario_map
    if scenario_id in scenario_map:
        raise ScenarioEditError(f"Scenario {scenario_id!r} already exists")

    if base_scenario_id is not None and base_scenario_id != BASELINE_SCENARIO_ID:
        if base_scenario_id not in scenario_map:
            raise ScenarioEditError(f"Unknown base scenario {base_scenario_id!r}")
        overlay = copy.deepcopy(scenario_map[base_scenario_id])
    else:
        # No base, or cloning BASELINE (the unmodified base config) -- either
        # way, a blank overlay: BASELINE has no overlay subtree of its own.
        overlay = CommentedMap()

    scenario_map[scenario_id] = overlay
    _save(cfg_path, data)
    return _overlay_yaml_text(overlay)


def read_scenario(cfg_path: Path, scenario_id: str) -> str:
    """Return one scenario overlay's YAML text (for the scoped editor)."""
    data = _load(cfg_path)
    scenario_map = data.get("scenarios") or {}
    if scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")
    return _overlay_yaml_text(scenario_map[scenario_id])


def update_scenario(cfg_path: Path, scenario_id: str, yaml_text: str) -> str:
    """Replace one scenario overlay's subtree from edited YAML text."""
    data = _load(cfg_path)
    scenario_map = data.get("scenarios")
    if not scenario_map or scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")
    try:
        parsed = load_yaml_string_with_comments(yaml_text)
    except Exception as exc:  # noqa: BLE001 — surfaced as a 422 to the editor
        raise ScenarioEditError(f"Invalid YAML: {exc}") from exc
    if parsed is not None and not isinstance(parsed, dict):
        raise ScenarioEditError("A scenario overlay must be a YAML mapping")
    scenario_map[scenario_id] = parsed if parsed is not None else CommentedMap()
    _save(cfg_path, data)
    return _overlay_yaml_text(scenario_map[scenario_id])


def _entity_location(raw: dict, entity_id: str) -> Optional[Tuple[str, Optional[str]]]:
    """Find *entity_id*'s declaration in the raw (pre-normalize) config.

    STONE v2 is authored as either one flat ``network:`` list, or one list
    per stage name (declared under ``stages:``, then repeated as its own
    top-level key holding that stage's items) — never a generic ``nodes:``/
    ``connections:`` + ``properties:`` shape, which only exists internally
    after normalization. Returns ``(list_key, kind_key)``: *list_key* is
    ``"network"`` or the stage name this entity's list lives under;
    *kind_key* is the STONE type key wrapping its properties (e.g.
    ``"Reservoir"``), or ``None`` for a kind-less logical connection
    (``source``+``target``, no type key). ``None`` overall if not found.
    """
    candidate_keys = (
        ["network"] if "network" in raw else list((raw.get("stages") or {}).keys())
    )
    for list_key in candidate_keys:
        items = raw.get(list_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("id") != entity_id:
                continue
            is_connection = "source" in item and "target" in item
            standard = _CONN_STANDARD_FIELDS if is_connection else _NODE_STANDARD_FIELDS
            kind_keys = [k for k in item if k not in standard and k != "id"]
            return list_key, (kind_keys[0] if kind_keys else None)
    return None


def update_scenario_entity(
    cfg_path: Path,
    scenario_id: str,
    entity_id: str,
    properties: dict,
) -> str:
    """Merge *properties* into one node/connection's overlay entry.

    Creates the scenario's per-stage (or ``network:``) overlay list and/or
    this entity's entry if they don't exist yet — the Properties panel's
    "Save" while a scenario is active calls this instead of touching the
    base network (see ``PropertiesPanel.tsx``), so a scenario's first-ever
    override starts from nothing. Only the given keys are written — callers
    are expected to have already diffed against the base value, so an
    unrelated field never gets duplicated into the overlay just because it
    happened to round-trip through an edit form.
    """
    if scenario_id == BASELINE_SCENARIO_ID:
        raise ScenarioEditError(
            "BASELINE has no overlay of its own — edit the base config instead"
        )
    if not properties:
        return read_scenario(cfg_path, scenario_id)

    data = _load(cfg_path)
    scenario_map = data.get("scenarios")
    if not scenario_map or scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")

    located = _entity_location(data, entity_id)
    if located is None:
        raise ScenarioEditError(
            f"Unknown node/connection {entity_id!r} in the base config"
        )
    list_key, kind_key = located

    overlay = scenario_map[scenario_id]
    if overlay is None:
        overlay = CommentedMap()
        scenario_map[scenario_id] = overlay

    entity_list = overlay.get(list_key)
    if entity_list is None:
        entity_list = CommentedSeq()
        overlay[list_key] = entity_list

    entry = next(
        (e for e in entity_list if isinstance(e, dict) and e.get("id") == entity_id),
        None,
    )
    if entry is None:
        entry = CommentedMap({"id": entity_id})
        entity_list.append(entry)

    if kind_key is not None:
        kind_props = entry.get(kind_key)
        if kind_props is None:
            kind_props = CommentedMap()
            entry[kind_key] = kind_props
        for key, value in properties.items():
            kind_props[key] = value
    else:
        # Kind-less logical connection -- properties (if any) sit directly
        # on the item, alongside id/source/target.
        for key, value in properties.items():
            entry[key] = value

    _save(cfg_path, data)
    return _overlay_yaml_text(overlay)


def rename_scenario(cfg_path: Path, scenario_id: str, new_id: str) -> None:
    """Rename a scenario's key. Note: moves it to the end of the mapping."""
    _validate_id(new_id)
    data = _load(cfg_path)
    scenario_map = data.get("scenarios")
    if not scenario_map or scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")
    if new_id in scenario_map:
        raise ScenarioEditError(f"Scenario {new_id!r} already exists")
    scenario_map[new_id] = scenario_map.pop(scenario_id)
    _save(cfg_path, data)


def delete_scenario(cfg_path: Path, scenario_id: str) -> None:
    """Remove a scenario overlay. The next sweep prunes its stale HDF5 group."""
    data = _load(cfg_path)
    scenario_map = data.get("scenarios")
    if not scenario_map or scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")
    del scenario_map[scenario_id]
    _save(cfg_path, data)
