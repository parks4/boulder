"""Tests for POST /api/sweep/run's `no_cache` passthrough.

The "Regenerate cache" action (Scenario Pane) reuses the plain "Run Sweep"
endpoint with ``no_cache: true``, which must set ``BOULDER_NO_CACHE=1`` in the
subprocess env so a cache-aware runner (e.g. ``bloc.scenario_sweep``) discards
its collection store instead of skipping unchanged scenarios.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402

_CONFIG_YAML = """\
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
scenario:
  a:
    metadata:
      scenario_name: "A"
"""


def _client_with_local_runner(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG_YAML, encoding="utf-8")
    (tmp_path / "run_sweep.py").write_text("", encoding="utf-8")

    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    app.state.preloaded_raw = {"scenario": {"a": {}}}
    return client, app


def _mock_popen_factory(started: threading.Event, captured: Dict[str, Any]):
    """Build a Popen stand-in that exits immediately with no output."""
    proc = MagicMock()
    proc.stdout = iter([])
    proc.wait.return_value = None
    proc.returncode = 0

    def _factory(*args: Any, **kwargs: Any) -> MagicMock:
        captured["kwargs"] = kwargs
        started.set()
        return proc

    return _factory


def test_sweep_run_default_does_not_set_no_cache_env(tmp_path: Path) -> None:
    client, _app = _client_with_local_runner(tmp_path)
    started = threading.Event()
    captured: Dict[str, Any] = {}
    try:
        with patch(
            "boulder.api.routes.sweep.subprocess.Popen",
            side_effect=_mock_popen_factory(started, captured),
        ):
            resp = client.post("/api/sweep/run", json={})
            assert resp.status_code == 200, resp.text
            assert started.wait(timeout=2), "subprocess.Popen was never called"
        assert "BOULDER_NO_CACHE" not in captured["kwargs"]["env"]
    finally:
        client.__exit__(None, None, None)


def test_sweep_run_no_body_also_does_not_set_no_cache_env(tmp_path: Path) -> None:
    """A client that omits the body entirely gets the same default as `{}`."""
    client, _app = _client_with_local_runner(tmp_path)
    started = threading.Event()
    captured: Dict[str, Any] = {}
    try:
        with patch(
            "boulder.api.routes.sweep.subprocess.Popen",
            side_effect=_mock_popen_factory(started, captured),
        ):
            resp = client.post("/api/sweep/run")
            assert resp.status_code == 200, resp.text
            assert started.wait(timeout=2), "subprocess.Popen was never called"
        assert "BOULDER_NO_CACHE" not in captured["kwargs"]["env"]
    finally:
        client.__exit__(None, None, None)


def test_sweep_run_no_cache_sets_env(tmp_path: Path) -> None:
    client, _app = _client_with_local_runner(tmp_path)
    started = threading.Event()
    captured: Dict[str, Any] = {}
    try:
        with patch(
            "boulder.api.routes.sweep.subprocess.Popen",
            side_effect=_mock_popen_factory(started, captured),
        ):
            resp = client.post("/api/sweep/run", json={"no_cache": True})
            assert resp.status_code == 200, resp.text
            assert started.wait(timeout=2), "subprocess.Popen was never called"
        assert captured["kwargs"]["env"].get("BOULDER_NO_CACHE") == "1"
    finally:
        client.__exit__(None, None, None)
