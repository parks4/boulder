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
    drop_legacy_metadata_keys,
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
metadata:
  description: "test config"
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
        # The authored `scenarios:` block survives untouched in the adopted raw
        # base -- the overlay's own legacy key is dropped when it is expanded.
        assert list(app.state.preloaded_raw["scenarios"]) == ["a"]
