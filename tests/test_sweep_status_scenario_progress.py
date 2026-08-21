"""Tests for `sweep_status`'s per-scenario `scenario_progress` map.

Run Sweep runs in-process now, one scenario at a time through the same
`SimulationWorker` `/api/simulations` uses (see `boulder/api/routes/sweep.py`)
-- no subprocess, no stdout parsing. These tests stand in for the real
`SimulationWorker` with a fake whose progress the test controls directly, so
`scenario_progress`/`last_line` transitions can be asserted deterministically
without running a real Cantera network.

`scenario_progress`: a `{scenario_id: {stage, stage_total, stage_id}}` map
(keyed by id, not a single "current scenario" scalar, so a future parallel
sweep could hold more than one entry at once without a shape change) that
`GET /api/sweep/status` passes straight through. `last_line` mirrors the most
recent progress message, for the frontend's "Calculating…" detail line, and
both clear the moment a scenario finishes (or the whole sweep stops).
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


# Two stages, so `scenario_progress` has something to count: `groups` comes out
# of validation in topological (== solve) order, which is what tells the route
# which stage is running -- the first one not yet completed.
_TWO_STAGE_YAML = """
metadata:
  description: "two-stage test config"
phases:
  gas:
    mechanism: gri30.yaml
stages:
  first:
    mechanism: gri30.yaml
    solver: advance_to_steady_state
  second:
    mechanism: gri30.yaml
    solver: advance_to_steady_state

first:
  - id: feed
    Reservoir:
      temperature: 298.15
      pressure: 101325
      composition: "CH4:1"

second:
  - id: feed2
    Reservoir:
      temperature: 298.15
      pressure: 101325
      composition: "CH4:1"
"""


def _client_with_config(tmp_path: Path, yaml_text: str = _CONFIG_YAML):
    from boulder.runner import BoulderRunner

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text, encoding="utf-8")

    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    # Mirrors what the app's startup lifespan would have loaded -- these
    # tests bypass that (no CLI arg was ever passed), so it's set directly.
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

    The test drives `.progress` directly instead of letting a real network
    build/solve, so scenario_progress transitions can be asserted
    deterministically and fast.
    """

    def __init__(self) -> None:
        self.progress = SimulationProgress()

    def start_simulation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_progress(self) -> SimulationProgress:
        return self.progress


def test_scenario_progress_tracks_stage_then_moves_to_the_next_scenario(
    tmp_path: Path,
) -> None:
    """A solving scenario's stage updates land in scenario_progress[id].

    A fresh scenario starts with no stage info of its own -- BASELINE (the
    unmodified base config) always solves first, then each named scenario.
    """
    client, app = _client_with_config(tmp_path, _TWO_STAGE_YAML)
    workers: List[_FakeWorker] = []

    def _factory() -> _FakeWorker:
        w = _FakeWorker()
        workers.append(w)
        return w

    try:
        with patch("boulder.simulation_worker.SimulationWorker", side_effect=_factory):
            resp = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp.status_code == 200, resp.text

            _wait_until(lambda: len(workers) >= 1)
            # Stage "first" is done, so stage 2 of 2 ("second") is the one now
            # solving -- what both the spinner headline and the tinted stage box
            # mean by "stage". Reporting the *finished* stage here made the
            # headline read "Stage 1/2" while the solver log line right
            # underneath already announced stage 2/2.
            workers[0].progress = SimulationProgress(
                stages_done=1, n_stages=2, completed_stage_ids=["first"]
            )
            _wait_until(
                lambda: app.state.sweep_job.get("scenario_progress", {})
                .get("BASELINE", {})
                .get("stage")
                == 2
            )
            assert app.state.sweep_job["scenario_progress"] == {
                "BASELINE": {"stage": 2, "stage_total": 2, "stage_id": "second"}
            }

            # BASELINE finishes -- the sweep moves on to "a".
            workers[0].progress = SimulationProgress(is_complete=True)
            _wait_until(lambda: len(workers) >= 2)
            _wait_until(lambda: app.state.sweep_job.get("current") == 2)
            # "a"'s freshly constructed worker hasn't reported stage counts
            # yet -- but its first stage is already the one solving.
            assert app.state.sweep_job["scenario_progress"] == {
                "a": {"stage": None, "stage_total": None, "stage_id": "first"}
            }

            workers[1].progress = SimulationProgress(is_complete=True)
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")
            assert app.state.sweep_job["scenario_progress"] == {}
            assert app.state.sweep_job["last_line"] is None
    finally:
        client.__exit__(None, None, None)


def test_last_line_follows_the_solver_s_own_log_lines(tmp_path: Path) -> None:
    """`last_line` tracks boulder's INFO logs, not just the scenario-start line.

    Written when a scenario *started* only, the detail line under the spinner sat
    on "scenario 1/2 (BASELINE)" for the whole solve while the console narrated
    stage after stage. It should say whatever the solver last said.
    """
    import logging

    client, app = _client_with_config(tmp_path)
    workers: List[_FakeWorker] = []

    def _factory() -> _FakeWorker:
        w = _FakeWorker()
        workers.append(w)
        return w

    try:
        with patch("boulder.simulation_worker.SimulationWorker", side_effect=_factory):
            resp = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp.status_code == 200, resp.text

            _wait_until(lambda: len(workers) >= 1)
            assert app.state.sweep_job["last_line"] == "scenario 1/2 (BASELINE)"

            # Any boulder.* logger, from any module in the solve path.
            logging.getLogger("boulder.staged_solver").info(
                "Staged solve: stage '%s' finished (%d/%d)", "pfr_stage", 3, 3
            )
            assert (
                app.state.sweep_job["last_line"]
                == "Staged solve: stage 'pfr_stage' finished (3/3)"
            )

            workers[0].progress = SimulationProgress(is_complete=True)
            _wait_until(lambda: len(workers) >= 2)
            workers[1].progress = SimulationProgress(is_complete=True)
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")
            assert app.state.sweep_job["last_line"] is None

            # Detached once the sweep is over -- a later log must not resurrect
            # a detail line for a job that finished.
            logging.getLogger("boulder.staged_solver").info("late straggler")
            assert app.state.sweep_job["last_line"] is None
    finally:
        client.__exit__(None, None, None)


def test_scenario_progress_clears_if_a_scenario_errors_mid_solve(
    tmp_path: Path,
) -> None:
    """A scenario that fails mid-solve still clears scenario_progress.

    Nothing is left "calculating" once the sweep has stopped, one way or another.
    """
    client, app = _client_with_config(tmp_path)
    workers: List[_FakeWorker] = []

    def _factory() -> _FakeWorker:
        w = _FakeWorker()
        workers.append(w)
        return w

    try:
        with patch("boulder.simulation_worker.SimulationWorker", side_effect=_factory):
            resp = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp.status_code == 200, resp.text

            _wait_until(lambda: len(workers) >= 1)
            workers[0].progress = SimulationProgress(
                stages_done=1, n_stages=1, completed_stage_ids=["default"]
            )
            _wait_until(
                lambda: app.state.sweep_job.get("scenario_progress", {})
                .get("BASELINE", {})
                .get("stage")
                == 1
            )
            # The only stage has finished, so no stage id is reported -- there
            # is nothing left solving for the graph to tint.
            assert app.state.sweep_job["scenario_progress"] == {
                "BASELINE": {"stage": 1, "stage_total": 1, "stage_id": None}
            }

            workers[0].progress = SimulationProgress(error_message="boom")
            _wait_until(lambda: app.state.sweep_job.get("status") == "error")
            assert app.state.sweep_job["scenario_progress"] == {}
            assert app.state.sweep_job["last_line"] is None
            assert "boom" in app.state.sweep_job["message"]
    finally:
        client.__exit__(None, None, None)
