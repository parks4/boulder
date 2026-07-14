"""Tests for scenario authoring: POST/PATCH/DELETE /api/scenarios*.

Unlike the read routes in ``test_scenario_focus.py`` (which serve precomputed
HDF5 trajectories), these edit the *source* config file's ``scenario:``
mapping on disk — the input side of the Scenario Pane's create/edit workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402

_BASE_YAML = """\
metadata:
  description: "test config"  # keep this comment
phases:
  gas:
    mechanism: gri30.yaml
network:
  - id: feed
    Reservoir:
      temperature: 298.15
      pressure: 101325
      composition: "CH4:1"
scenario:
  base_case:
    metadata:
      scenario_name: "Base Case"
    network:
      - id: feed
        Reservoir:
          temperature: 320.0
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_BASE_YAML, encoding="utf-8")
    return cfg


def _client_with_config(cfg_path: Path):
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg_path)
    return client, app


def _scenario_ids(cfg_path: Path) -> List[str]:
    from boulder.scenario_editor import list_scenario_ids

    return list_scenario_ids(cfg_path)


def test_create_scenario_requires_config_path() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = None
        resp = client.post("/api/scenarios", json={"scenario_id": "new1"})
        assert resp.status_code == 400


def test_create_scenario_blank(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, app = _client_with_config(cfg)
    try:
        resp = client.post("/api/scenarios", json={"scenario_id": "new1"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["scenario_id"] == "new1"
        assert _scenario_ids(cfg) == ["base_case", "new1"]
        # preloaded_raw refreshed so Run Sweep sees the new scenario immediately.
        assert "new1" in (app.state.preloaded_raw.get("scenario") or {})
        # The pre-existing comment elsewhere in the file survives.
        assert "keep this comment" in cfg.read_text(encoding="utf-8")
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_clone(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, app = _client_with_config(cfg)
    try:
        resp = client.post(
            "/api/scenarios",
            json={"scenario_id": "clone1", "base_scenario_id": "base_case"},
        )
        assert resp.status_code == 200, resp.text
        assert "scenario_name:" in resp.json()["yaml"]
        assert "Base Case" in resp.json()["yaml"]
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_duplicate_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post("/api/scenarios", json={"scenario_id": "base_case"})
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_bad_id_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post("/api/scenarios", json={"scenario_id": "bad id!"})
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_unknown_base_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post(
            "/api/scenarios",
            json={"scenario_id": "new1", "base_scenario_id": "nope"},
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_get_scenario_source(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.get("/api/scenarios/base_case/source")
        assert resp.status_code == 200
        assert "scenario_name" in resp.json()["yaml"]
    finally:
        client.__exit__(None, None, None)


def test_get_scenario_source_unknown_404(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.get("/api/scenarios/nope/source")
        assert resp.status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_update_scenario(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, app = _client_with_config(cfg)
    try:
        new_yaml = (
            "metadata:\n  scenario_name: Updated\n"
            "network:\n  - id: feed\n    Reservoir:\n      temperature: 350.0\n"
        )
        resp = client.patch("/api/scenarios/base_case", json={"yaml": new_yaml})
        assert resp.status_code == 200, resp.text
        assert "Updated" in resp.json()["yaml"]
        assert "350.0" in cfg.read_text(encoding="utf-8")
        assert (
            app.state.preloaded_raw["scenario"]["base_case"]["metadata"][
                "scenario_name"
            ]
            == "Updated"
        )
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_invalid_yaml_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.patch(
            "/api/scenarios/base_case", json={"yaml": "not: [valid: yaml"}
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_unknown_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.patch("/api/scenarios/nope", json={"yaml": "a: 1"})
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_rename_scenario(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.patch(
            "/api/scenarios/base_case/rename", json={"new_id": "renamed"}
        )
        assert resp.status_code == 200, resp.text
        assert _scenario_ids(cfg) == ["renamed"]
    finally:
        client.__exit__(None, None, None)


def test_delete_scenario(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, app = _client_with_config(cfg)
    try:
        resp = client.delete("/api/scenarios/base_case")
        assert resp.status_code == 200, resp.text
        assert _scenario_ids(cfg) == []
        assert not (app.state.preloaded_raw.get("scenario") or {})
    finally:
        client.__exit__(None, None, None)


def test_delete_scenario_unknown_404(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.delete("/api/scenarios/nope")
        assert resp.status_code == 404
    finally:
        client.__exit__(None, None, None)
