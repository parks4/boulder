"""Tests for GET /api/scenarios/{id}/preview.

Unlike `/scenarios/{id}` (a precomputed HDF5 trajectory — 404s until a sweep has
solved it), `/preview` deep-merges an authored scenario's overlay onto the base
config and returns the effective node/connection properties, so the GUI's Inputs
pane can show a scenario's parameter overrides before it has ever been solved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402

_BASE_YAML = """\
metadata:
  description: "test config"
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
  base_case:
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


def _client_fully_preloaded(cfg_path: Path):
    """Preload as the real app startup path would (populates `preloaded_raw`)."""
    import os

    os.environ["BOULDER_CONFIG_PATH"] = str(cfg_path)
    try:
        app = create_app()
        client = TestClient(app)
        client.__enter__()
    finally:
        del os.environ["BOULDER_CONFIG_PATH"]
    return client, app


def _node(body: dict, node_id: str) -> dict:
    return next(n for n in body["nodes"] if n["id"] == node_id)


def test_preview_authored_scenario_overrides_property(tmp_path: Path) -> None:
    """An authored (never-swept) scenario's overlay shows up in the preview."""
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.get("/api/scenarios/base_case/preview")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["scenario_id"] == "base_case"
        assert _node(body, "feed")["properties"]["temperature"] == 320.0
    finally:
        client.__exit__(None, None, None)


def test_preview_baseline_returns_unmodified_base_values(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.get("/api/scenarios/BASELINE/preview")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _node(body, "feed")["properties"]["temperature"] == 298.15
    finally:
        client.__exit__(None, None, None)


def test_preview_unknown_scenario_404(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.get("/api/scenarios/nope/preview")
        assert resp.status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_preview_without_a_config_404() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = None
        resp = client.get("/api/scenarios/base_case/preview")
        assert resp.status_code == 404


def test_preview_falls_back_to_disk_when_preloaded_raw_is_unset(tmp_path: Path) -> None:
    """The `preloaded_config_path`-only setup (as in scenario-editing tests) still works.

    `preloaded_raw` isn't populated until a scenario CRUD call reloads it, but
    the preview route must not depend on that having happened yet.
    """
    cfg = _write_config(tmp_path)
    client, app = _client_with_config(cfg)
    try:
        assert app.state.preloaded_raw is None
        resp = client.get("/api/scenarios/base_case/preview")
        assert resp.status_code == 200, resp.text
        assert _node(resp.json(), "feed")["properties"]["temperature"] == 320.0
    finally:
        client.__exit__(None, None, None)


def test_preview_reflects_fully_preloaded_app_state(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_fully_preloaded(cfg)
    try:
        resp = client.get("/api/scenarios/base_case/preview")
        assert resp.status_code == 200, resp.text
        assert _node(resp.json(), "feed")["properties"]["temperature"] == 320.0
    finally:
        client.__exit__(None, None, None)
