"""Legacy ``metadata:`` keys are discarded on load, not rejected.

``metadata.scenario_id`` and ``metadata.scenario_name`` were removed from the
STONE vocabulary. ``MetadataModel`` is ``extra="forbid"``, so without a compat
step every file authored against an older release would fail validation with
an ``extra_forbidden`` error. :func:`boulder.config.normalize_config` drops the
keys first (with a warning naming them), for the base config, for every
expanded scenario, and for a config uploaded through the API.
"""

from __future__ import annotations

import copy
import logging

import pytest

from boulder.config import (
    LEGACY_METADATA_KEYS,
    STONE_FORMAT_VERSION,
    drop_legacy_metadata_keys,
    merge_config_into_yaml,
    migrate_stone_config,
    normalize_config,
    validate_config,
)
from boulder.runset import expand_scenarios

_LEGACY_CONFIG = {
    "metadata": {
        "description": "test config",
        "scenario_id": "old_id",
        "scenario_name": "Old display name",
    },
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "network": [
        {
            "id": "feed",
            "Reservoir": {
                "temperature": 298.15,
                "pressure": 101325,
                "composition": "CH4:1",
            },
        }
    ],
}

_LEGACY_YAML = """\
# keep me: a file-level comment that must survive the GUI round-trip
metadata:
  description: "test config"  # keep me too
  scenario_id: old_id
  scenario_name: "Old display name"
phases:
  gas:
    mechanism: gri30.yaml
network:
  - id: feed
    Reservoir:
      temperature: 298.15
      pressure: 101325
      composition: "CH4:1"
scenarios:
  a:
    metadata:
      scenario_name: "A"
"""


@pytest.fixture
def config_log(caplog):
    """``caplog`` wired to ``boulder.config`` directly.

    Boulder's console logging gives the ``boulder`` logger its own handler and
    switches propagation off, so records never reach caplog's root handler.
    """
    lg = logging.getLogger("boulder.config")
    lg.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="boulder.config"):
            yield caplog
    finally:
        lg.removeHandler(caplog.handler)


def test_normalize_drops_legacy_keys_and_warns(config_log):
    caplog = config_log
    normalized = normalize_config(copy.deepcopy(_LEGACY_CONFIG))

    for key in LEGACY_METADATA_KEYS:
        assert key not in normalized["metadata"]
    assert normalized["metadata"]["description"] == "test config"
    # Validation now passes -- the whole point of dropping them first.
    validate_config(normalized)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("metadata.scenario_id" in w and "old_id" in w for w in warnings)
    assert any(
        "metadata.scenario_name" in w and "Old display name" in w for w in warnings
    )


def test_clean_config_is_left_alone(config_log):
    caplog = config_log
    clean = copy.deepcopy(_LEGACY_CONFIG)
    for key in LEGACY_METADATA_KEYS:
        clean["metadata"].pop(key)
    assert drop_legacy_metadata_keys(clean) == []
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert drop_legacy_metadata_keys({"phases": {}}) == []  # no metadata block


def test_scenario_overlay_legacy_name_still_expands_and_validates():
    import yaml

    raw = yaml.safe_load(_LEGACY_YAML)
    runs = dict(expand_scenarios(raw))
    assert set(runs) == {"BASELINE", "a"}
    for cfg in runs.values():
        normalized = normalize_config(copy.deepcopy(cfg))
        validate_config(normalized)
        for key in LEGACY_METADATA_KEYS:
            assert key not in normalized["metadata"]


def test_upload_of_legacy_yaml_is_accepted():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from boulder.api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/configs/upload",
            files={"file": ("legacy.yaml", _LEGACY_YAML, "application/x-yaml")},
        )
        assert resp.status_code == 200, resp.text
        meta = resp.json()["config"]["metadata"]
        for key in LEGACY_METADATA_KEYS:
            assert key not in meta
        # The adopted raw base is the file exactly as authored (legacy keys
        # included -- they are dropped when a scenario is expanded); the
        # validated config is stamped and the notices travel to the browser.
        raw = app.state.preloaded_raw
        assert list(raw["scenarios"]) == ["a"]
        assert "stone_version" not in raw["metadata"]
        assert meta["stone_version"] == STONE_FORMAT_VERSION
        warnings = resp.json()["warnings"]
        assert any("metadata.scenario_id" in w for w in warnings)
        assert any("scenarios.a.metadata.scenario_name" in w for w in warnings)


def test_migrate_reports_legacy_keys_in_base_and_overlays():
    import yaml

    raw = yaml.safe_load(_LEGACY_YAML)
    notices = migrate_stone_config(raw)
    assert raw["metadata"]["stone_version"] == STONE_FORMAT_VERSION
    for key in LEGACY_METADATA_KEYS:
        assert key not in raw["metadata"]
    assert raw["scenarios"]["a"]["metadata"] == {}
    assert len(notices) == 3
    # Second pass: nothing left to do.
    assert migrate_stone_config(raw) == []


def test_gui_round_trip_yields_a_current_stone_file():
    """Upload old -> YAML pane (sync) -> Download produces a migrated file.

    The YAML pane text is ``merge_config_into_yaml(live_config, original)``;
    it must lose the legacy keys, gain ``stone_version`` and keep comments.
    """
    import yaml

    raw = yaml.safe_load(_LEGACY_YAML)
    validated = validate_config(normalize_config(copy.deepcopy(raw)))
    out, warnings = merge_config_into_yaml(validated, _LEGACY_YAML)

    assert "scenario_id" not in out
    assert "scenario_name" not in out
    assert "# keep me: a file-level comment" in out
    assert "# keep me too" in out
    assert any("scenario_id" in w for w in warnings)
    reloaded = yaml.safe_load(out)
    assert reloaded["metadata"]["stone_version"] == STONE_FORMAT_VERSION  # a str
    assert reloaded["scenarios"]["a"]["metadata"] == {}
    # Re-syncing the migrated file is quiet.
    _, warnings2 = merge_config_into_yaml(validated, out)
    assert warnings2 == []


def test_sync_creates_metadata_block_when_missing():
    original = _LEGACY_YAML.split("phases:", 1)[1]
    original = "phases:" + original.split("scenarios:")[0]
    assert "metadata" not in original
    import yaml

    validated = validate_config(normalize_config(yaml.safe_load(original)))
    out, _ = merge_config_into_yaml(validated, original)
    assert out.lstrip().startswith("metadata:")
    assert yaml.safe_load(out)["metadata"] == {"stone_version": STONE_FORMAT_VERSION}
