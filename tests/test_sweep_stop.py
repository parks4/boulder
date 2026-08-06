"""Tests for cooperative sweep cancellation (`POST /api/sweep/stop`).

Run Sweep runs in-process, one scenario at a time through the same
`SimulationWorker` a plain "Run Simulation" uses (see `boulder/api/routes/
sweep.py`) -- no subprocess, so there is nothing to kill. Stop reuses
exactly the mechanism tests/test_simulation_stop.py exercises for a single
run: `solve_scenario` (boulder/sweep_runner.py) is handed a `stop_event` and
checks it in its own poll loop, calling `worker.stop_simulation()` on the
scenario currently in flight; the sweep's own scenario loop checks the same
event before starting the next one.

Like test_sweep_status_scenario_progress.py, these stand a fake in for
SimulationWorker so scenario transitions can be driven deterministically
without a real Cantera solve.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, List
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.api.routes.sweep import _run_host_sweep  # noqa: E402
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
    """Stand-in for SimulationWorker.

    Records whether stop_simulation() was called instead of actually
    stopping anything (there's no real thread).
    """

    def __init__(self) -> None:
        self.progress = SimulationProgress()
        self.stop_calls = 0

    def start_simulation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_progress(self) -> SimulationProgress:
        return self.progress

    def stop_simulation(self) -> None:
        self.stop_calls += 1
        self.progress.is_stopping = True


def _sweep_with_fake_workers(tmp_path: Path, scenarios: dict):
    """Start a sweep with SimulationWorker faked out; return (client, app, workers)."""
    client, app = _client_with_config(tmp_path)
    workers: List[_FakeWorker] = []

    def _factory() -> _FakeWorker:
        w = _FakeWorker()
        workers.append(w)
        return w

    patcher = patch("boulder.simulation_worker.SimulationWorker", side_effect=_factory)
    patcher.start()
    resp = client.post("/api/sweep/run", json={"scenarios": scenarios})
    assert resp.status_code == 200, resp.text
    return client, app, workers, patcher


class TestSweepStopEndpoint:
    def test_404_when_no_sweep_is_running(self, tmp_path: Path) -> None:
        client, app = _client_with_config(tmp_path)
        try:
            resp = client.post("/api/sweep/stop")
            assert resp.status_code == 404
        finally:
            client.__exit__(None, None, None)

    def test_returns_immediately_and_marks_status_stopping(
        self, tmp_path: Path
    ) -> None:
        client, app, workers, patcher = _sweep_with_fake_workers(tmp_path, {"a": {}})
        try:
            _wait_until(lambda: len(workers) >= 1)

            started = time.perf_counter()
            resp = client.post("/api/sweep/stop")
            elapsed = time.perf_counter() - started

            assert resp.status_code == 200
            assert resp.json() == {"stopping": True}
            assert elapsed < 1.0
            assert app.state.sweep_job["status"] == "stopping"
        finally:
            patcher.stop()
            client.__exit__(None, None, None)

    def test_stop_calls_stop_simulation_on_the_in_flight_worker(
        self, tmp_path: Path
    ) -> None:
        client, app, workers, patcher = _sweep_with_fake_workers(tmp_path, {"a": {}})
        try:
            _wait_until(lambda: len(workers) >= 1)
            resp = client.post("/api/sweep/stop")
            assert resp.status_code == 200

            _wait_until(lambda: workers[0].stop_calls >= 1)
        finally:
            patcher.stop()
            client.__exit__(None, None, None)

    def test_stop_prevents_the_next_scenario_from_starting(
        self, tmp_path: Path
    ) -> None:
        """BASELINE is in flight; stopping must not let scenario "a" start."""
        client, app, workers, patcher = _sweep_with_fake_workers(tmp_path, {"a": {}})
        try:
            _wait_until(lambda: len(workers) >= 1)
            resp = client.post("/api/sweep/stop")
            assert resp.status_code == 200

            _wait_until(lambda: app.state.sweep_job.get("status") == "cancelled")
            assert len(workers) == 1  # scenario "a" never started
            assert app.state.sweep_job["scenario_progress"] == {}
        finally:
            patcher.stop()
            client.__exit__(None, None, None)

    def test_cancelled_status_not_error(self, tmp_path: Path) -> None:
        """A stopped sweep must be distinguishable from a genuinely failed one."""
        client, app, workers, patcher = _sweep_with_fake_workers(tmp_path, {"a": {}})
        try:
            _wait_until(lambda: len(workers) >= 1)
            resp = client.post("/api/sweep/stop")
            assert resp.status_code == 200

            _wait_until(lambda: app.state.sweep_job.get("status") == "cancelled")
            assert app.state.sweep_job["status"] != "error"
        finally:
            patcher.stop()
            client.__exit__(None, None, None)

    def test_second_run_rejected_while_stopping(self, tmp_path: Path) -> None:
        client, app, workers, patcher = _sweep_with_fake_workers(tmp_path, {"a": {}})
        try:
            _wait_until(lambda: len(workers) >= 1)
            resp = client.post("/api/sweep/stop")
            assert resp.status_code == 200
            assert app.state.sweep_job["status"] == "stopping"

            resp = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp.status_code == 409
        finally:
            patcher.stop()
            client.__exit__(None, None, None)


class TestHostRunnerStopEventKwarg:
    """`_run_host_sweep` extends its existing signature-detection.

    It now also detects `stop_event`, the same way it already does for
    `progress`/`config_path`.
    """

    def test_stop_event_passed_when_the_runner_declares_it(
        self, tmp_path: Path
    ) -> None:
        received = {}

        def runner(store_dir, stop_event=None):
            received["stop_event"] = stop_event

        sentinel = threading.Event()

        # _run_host_sweep resolves `dotted` via resolve_dotted_path -- patch
        # that to hand back this in-test callable instead of a real import.
        with patch(
            "boulder.cantera_converter.resolve_dotted_path", return_value=runner
        ):
            _run_host_sweep(
                "unused.dotted.path",
                state={"current": 0, "total": 0, "message": "", "last_line": None},
                store_dir=tmp_path,
                stop_event=sentinel,
            )

        assert received["stop_event"] is sentinel

    def test_stop_event_omitted_when_the_runner_does_not_declare_it(
        self, tmp_path: Path
    ) -> None:
        received = {}

        def runner(store_dir):
            received["called"] = True

        with patch(
            "boulder.cantera_converter.resolve_dotted_path", return_value=runner
        ):
            _run_host_sweep(
                "unused.dotted.path",
                state={"current": 0, "total": 0, "message": "", "last_line": None},
                store_dir=tmp_path,
                stop_event=threading.Event(),
            )

        assert received == {"called": True}
