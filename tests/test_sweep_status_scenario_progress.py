"""Tests for `sweep_status`'s per-scenario `scenario_progress` map.

`sweep_runner.run()` already prints the scenario id inline
("scenario N/M (id)", or "... (id): cached, skipped" for a cache hit), and
`boulder.staged_solver`'s per-stage INFO logs reach the same captured
subprocess output. `sweep.py`'s stdout parser turns those lines into
`scenario_progress`: a `{scenario_id: {stage, stage_total, stage_id}}` map (keyed by id,
not a single "current scenario" scalar, so a future parallel sweep runner can
hold more than one entry at once without a shape change) that
`GET /api/sweep/status` passes straight through.

Also covers `last_line`: the runner's most recent non-empty stdout line, kept
verbatim for the frontend's "Calculating…" detail line and cleared once the
subprocess exits.
"""

from __future__ import annotations

import threading
import time
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
scenarios:
  a:
    metadata:
      scenario_name: "A"
  b:
    metadata:
      scenario_name: "B"
"""


def _client_with_local_runner(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG_YAML, encoding="utf-8")
    (tmp_path / "run_sweep.py").write_text("", encoding="utf-8")

    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    app.state.preloaded_raw = {"scenarios": {"a": {}, "b": {}}}
    return client, app


def test_scenario_progress_tracks_stage_then_clears_on_skip(tmp_path: Path) -> None:
    """A solving scenario's stage updates land in scenario_progress[id].

    A subsequent "cached, skipped" scenario line clears the map instead of
    ever showing that scenario as "calculating" (a cache hit is instant).
    `last_line` holds the runner's latest stdout line verbatim while solving.
    """
    client, app = _client_with_local_runner(tmp_path)
    after_stage_line = threading.Event()
    resume_after_stage = threading.Event()
    after_skip_line = threading.Event()

    def stdout_gen():
        yield "scenario 1/2 (a)"
        yield (
            "2026-01-01 00:00:00 - boulder.staged_solver - INFO - "
            "Staged solve: stage 'default' (1/3, 3 reactors)"
        )
        # Pause here (holding the for-loop mid-iteration) so the test can
        # assert the in-flight state before the next line arrives.
        after_stage_line.set()
        resume_after_stage.wait(timeout=5)
        yield "scenario 2/2 (b): cached, skipped"
        after_skip_line.set()

    proc = MagicMock()
    proc.stdout = stdout_gen()
    proc.wait.return_value = None
    proc.returncode = 0
    captured: Dict[str, Any] = {}

    def _factory(*args: Any, **kwargs: Any) -> MagicMock:
        captured["kwargs"] = kwargs
        return proc

    try:
        with patch("boulder.api.routes.sweep.subprocess.Popen", side_effect=_factory):
            resp = client.post("/api/sweep/run", json={})
            assert resp.status_code == 200, resp.text

            assert after_stage_line.wait(timeout=2), "stage line was never processed"
            job = app.state.sweep_job
            assert job["scenario_progress"] == {
                "a": {"stage": 1, "stage_total": 3, "stage_id": "default"}
            }
            assert job["last_line"] == (
                "2026-01-01 00:00:00 - boulder.staged_solver - INFO - "
                "Staged solve: stage 'default' (1/3, 3 reactors)"
            )

            resume_after_stage.set()
            assert after_skip_line.wait(timeout=2), "skip line was never processed"
            assert app.state.sweep_job["scenario_progress"] == {}

            status = client.get("/api/sweep/status").json()
            assert status["scenario_progress"] == {}
            assert status["current"] == 2
            assert status["total"] == 2
    finally:
        client.__exit__(None, None, None)


def test_scenario_progress_clears_once_the_process_exits_mid_solve(
    tmp_path: Path,
) -> None:
    """The last scenario solved may not end with a "cached, skipped" line.

    Nothing should linger as "calculating" once the subprocess has exited,
    one way or another.
    """
    client, app = _client_with_local_runner(tmp_path)
    after_stage_line = threading.Event()
    resume_after_stage = threading.Event()

    def stdout_gen():
        yield "scenario 1/1 (a)"
        yield (
            "2026-01-01 00:00:00 - boulder.staged_solver - INFO - "
            "Staged solve: stage 'default' (1/1, 3 reactors)"
        )
        after_stage_line.set()
        resume_after_stage.wait(timeout=5)

    proc = MagicMock()
    proc.stdout = stdout_gen()
    proc.wait.return_value = None
    proc.returncode = 0

    try:
        with patch("boulder.api.routes.sweep.subprocess.Popen", return_value=proc):
            resp = client.post("/api/sweep/run", json={})
            assert resp.status_code == 200, resp.text

            assert after_stage_line.wait(timeout=2), "stage line was never processed"
            assert app.state.sweep_job["scenario_progress"] == {
                "a": {"stage": 1, "stage_total": 1, "stage_id": "default"}
            }

            resume_after_stage.set()  # let stdout end -> proc.wait() -> "done"

            for _ in range(50):
                if app.state.sweep_job.get("status") == "done":
                    break
                time.sleep(0.05)
            assert app.state.sweep_job["status"] == "done"
            assert app.state.sweep_job["scenario_progress"] == {}
            assert app.state.sweep_job["last_line"] is None
    finally:
        client.__exit__(None, None, None)
