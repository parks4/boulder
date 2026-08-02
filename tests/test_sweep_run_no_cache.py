"""Tests for POST /api/sweep/run's `no_cache` behavior.

Run Sweep runs in-process now (see `boulder/api/routes/sweep.py`) -- `no_cache`
deletes the collection store before running instead of setting an env var for
a subprocess, so a cache-aware host discards unchanged-fingerprint skips and
re-solves every scenario. These tests stand in for `SimulationWorker` with a
fake (see `test_sweep_status_scenario_progress.py`) so caching behavior can be
asserted without a real Cantera solve.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, List
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.simulation_worker import SimulationProgress  # noqa: E402

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
"""


def _client_with_config(tmp_path: Path):
    from boulder.runner import BoulderRunner

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG_YAML, encoding="utf-8")

    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    app.state.preloaded_raw = BoulderRunner.load(str(cfg))
    return client, app


def _wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met within timeout")


class _FakeWorker:
    """Completes instantly -- these tests care about caching, not progress."""

    def __init__(self) -> None:
        self.progress = SimulationProgress(is_complete=True)

    def start_simulation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_progress(self) -> SimulationProgress:
        return self.progress


def test_sweep_run_reuses_the_cache_when_unchanged(tmp_path: Path) -> None:
    """A second run of the same config skips every scenario (fingerprint match)."""
    client, app = _client_with_config(tmp_path)
    calls: List[None] = []

    def _factory() -> _FakeWorker:
        calls.append(None)
        return _FakeWorker()

    try:
        with patch("boulder.api.routes.sweep.SimulationWorker", side_effect=_factory):
            resp1 = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp1.status_code == 200, resp1.text
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")
            # Two runs: BASELINE (unmodified base) + "a".
            assert len(calls) == 2

            resp2 = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp2.status_code == 200, resp2.text
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")
            assert len(calls) == 2  # unchanged config -- nothing re-solved
    finally:
        client.__exit__(None, None, None)


def test_sweep_run_no_cache_forces_a_full_recompute(tmp_path: Path) -> None:
    client, app = _client_with_config(tmp_path)
    calls: List[None] = []

    def _factory() -> _FakeWorker:
        calls.append(None)
        return _FakeWorker()

    try:
        with patch("boulder.api.routes.sweep.SimulationWorker", side_effect=_factory):
            resp1 = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp1.status_code == 200, resp1.text
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")
            assert len(calls) == 2

            resp2 = client.post(
                "/api/sweep/run", json={"scenarios": {"a": {}}, "no_cache": True}
            )
            assert resp2.status_code == 200, resp2.text
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")
            assert len(calls) == 4  # store wiped first -- both re-solved
    finally:
        client.__exit__(None, None, None)


def test_sweep_run_rejects_a_second_run_while_one_is_in_flight(tmp_path: Path) -> None:
    client, app = _client_with_config(tmp_path)
    workers: List[_FakeWorker] = []

    def _factory() -> _FakeWorker:
        w = _FakeWorker()
        w.progress = SimulationProgress()  # starts un-complete -- "in flight"
        workers.append(w)
        return w

    try:
        with patch("boulder.api.routes.sweep.SimulationWorker", side_effect=_factory):
            resp1 = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp1.status_code == 200, resp1.text
            _wait_until(lambda: app.state.sweep_job.get("status") == "running")

            resp2 = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp2.status_code == 409

            # Let the in-flight sweep's background thread actually finish
            # (still inside the patch -- every remaining scenario's worker
            # must be a fake too, including ones not constructed yet) instead
            # of leaking a "while True: time.sleep(0.3)" daemon thread that
            # would otherwise keep running, and competing for the GIL, for
            # the rest of this process's test session.
            for _ in range(200):
                if app.state.sweep_job.get("status") in ("done", "error"):
                    break
                for w in list(workers):
                    w.progress = SimulationProgress(is_complete=True)
                time.sleep(0.05)
            assert app.state.sweep_job.get("status") == "done"
    finally:
        client.__exit__(None, None, None)
