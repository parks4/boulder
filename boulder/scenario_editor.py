"""Scenario authoring: create/update/delete a named ``scenario:`` overlay on disk.

Complements :mod:`boulder.api.routes.scenarios` (which only *reads* precomputed
trajectories from the HDF5 scenario store) with the input side of the Scenario
Pane: creating a new scenario adds a new named overlay, editing it changes
only that overlay's subtree, and ``Run Sweep`` is what turns overlays into
trajectories.

Every function here mutates only the targeted ``scenario.<id>`` subtree of the
YAML on disk via ``ruamel.yaml`` — nodes, connections, settings, and comments
elsewhere in the file are left untouched.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, List, Optional

from ruamel.yaml.comments import CommentedMap

from .config import (
    get_yaml_with_comments,
    load_config_file_with_comments,
    load_yaml_string_with_comments,
    yaml_to_string_with_comments,
)

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class ScenarioEditError(ValueError):
    """Invalid scenario id / body / operation — routes map this to HTTP 4xx."""


def _validate_id(scenario_id: str) -> None:
    if not scenario_id or not _ID_RE.match(scenario_id):
        raise ScenarioEditError(
            f"Invalid scenario id {scenario_id!r}: use letters, digits, "
            "'_' or '-' only"
        )


def _load(cfg_path: Path) -> CommentedMap:
    data = load_config_file_with_comments(str(cfg_path))
    if not isinstance(data, dict):
        raise ScenarioEditError(f"{cfg_path} does not contain a YAML mapping")
    return data


def _save(cfg_path: Path, data: CommentedMap) -> None:
    yaml_obj = get_yaml_with_comments()
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml_obj.dump(data, f)


def _overlay_yaml_text(overlay: Any) -> str:
    return yaml_to_string_with_comments(overlay if overlay is not None else CommentedMap())


def list_scenario_ids(cfg_path: Path) -> List[str]:
    """Return the ``scenario:`` mapping's keys, in file order."""
    data = _load(cfg_path)
    scenario_map = data.get("scenario") or {}
    return list(scenario_map.keys())


def create_scenario(
    cfg_path: Path, scenario_id: str, base_scenario_id: Optional[str] = None
) -> str:
    """Add a new (blank or cloned) scenario overlay. Returns its YAML text."""
    _validate_id(scenario_id)
    data = _load(cfg_path)
    scenario_map = data.get("scenario")
    if scenario_map is None:
        scenario_map = CommentedMap()
        data["scenario"] = scenario_map
    if scenario_id in scenario_map:
        raise ScenarioEditError(f"Scenario {scenario_id!r} already exists")

    if base_scenario_id is not None:
        if base_scenario_id not in scenario_map:
            raise ScenarioEditError(f"Unknown base scenario {base_scenario_id!r}")
        overlay = copy.deepcopy(scenario_map[base_scenario_id])
    else:
        overlay = CommentedMap()

    scenario_map[scenario_id] = overlay
    _save(cfg_path, data)
    return _overlay_yaml_text(overlay)


def read_scenario(cfg_path: Path, scenario_id: str) -> str:
    """Return one scenario overlay's YAML text (for the scoped editor)."""
    data = _load(cfg_path)
    scenario_map = data.get("scenario") or {}
    if scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")
    return _overlay_yaml_text(scenario_map[scenario_id])


def update_scenario(cfg_path: Path, scenario_id: str, yaml_text: str) -> str:
    """Replace one scenario overlay's subtree from edited YAML text."""
    data = _load(cfg_path)
    scenario_map = data.get("scenario")
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


def rename_scenario(cfg_path: Path, scenario_id: str, new_id: str) -> None:
    """Rename a scenario's key. Note: moves it to the end of the mapping."""
    _validate_id(new_id)
    data = _load(cfg_path)
    scenario_map = data.get("scenario")
    if not scenario_map or scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")
    if new_id in scenario_map:
        raise ScenarioEditError(f"Scenario {new_id!r} already exists")
    scenario_map[new_id] = scenario_map.pop(scenario_id)
    _save(cfg_path, data)


def delete_scenario(cfg_path: Path, scenario_id: str) -> None:
    """Remove a scenario overlay. The next sweep prunes its stale HDF5 group."""
    data = _load(cfg_path)
    scenario_map = data.get("scenario")
    if not scenario_map or scenario_id not in scenario_map:
        raise ScenarioEditError(f"Unknown scenario {scenario_id!r}")
    del scenario_map[scenario_id]
    _save(cfg_path, data)
