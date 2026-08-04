"""What Run Sweep writes, the Scenario pane must be able to read.

The one assertion that crosses the writer/reader boundary. Sweep tests check the
store the sweep itself wrote; scenario-route tests seed a store directly. Neither
notices if the two ever stop agreeing about *where* results live — which is
exactly how a reader/writer split can pass a full green suite while the GUI shows
"Not computed yet" for a sweep that just finished.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("h5py")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.runner import BoulderRunner  # noqa: E402
from boulder.simulation_worker import SimulationProgress  # noqa: E402

_CONFIG = """\
metadata:
  description: "sweep -> pane"
phases:
  gas:
    mechanism: gri30.yaml
network:
- id: feed
  Reservoir:
    temperature: 300 K
    pressure: 101325 Pa
    composition: "CH4:1"
scenarios:
  hot: {metadata: {description: hotter}}
  cold: {metadata: {description: colder}}
"""


class _FakeWorker:
    """Completes instantly — this is about plumbing, not solving."""

    def __init__(self) -> None:
        self.progress = SimulationProgress(is_complete=True)

    def start_simulation(self, *a: Any, **kw: Any) -> None:
        pass

    def get_progress(self) -> SimulationProgress:
        return self.progress


class _StubConverter:
    def __init__(self, mechanism: Any = None, plugins: Any = None) -> None:
        self.mechanism = mechanism

    def resolve_mechanism(self, name: str) -> str:
        return name


def _client(tmp_path: Path):
    cfg = tmp_path / "model.yaml"
    cfg.write_text(_CONFIG, encoding="utf-8")
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    app.state.preloaded_raw = BoulderRunner.load(str(cfg))
    app.state.converter_class = _StubConverter
    return client, app


def _run_sweep(client: TestClient, app: Any, overlays: Dict[str, Any]) -> None:
    with patch(
        "boulder.simulation_worker.SimulationWorker", side_effect=lambda: _FakeWorker()
    ):
        resp = client.post("/api/sweep/run", json={"scenarios": overlays})
        assert resp.status_code == 200, resp.text
        deadline = time.time() + 20.0
        while time.time() < deadline:
            if app.state.sweep_job.get("status") in ("done", "error"):
                break
            time.sleep(0.02)
    assert app.state.sweep_job.get("status") == "done", app.state.sweep_job


def test_a_finished_sweep_is_visible_to_the_scenario_pane(tmp_path: Path) -> None:
    """The regression this file exists for: writer and reader must agree."""
    client, app = _client(tmp_path)
    try:
        overlays = client.get("/api/scenarios").json()["authored_overlays"]
        _run_sweep(client, app, overlays)

        listed = client.get("/api/scenarios").json()
        ids = {e["id"] for e in listed["scenarios"]}
        assert ids == {"BASELINE", "hot", "cold"}, (
            "Run Sweep wrote results the Scenario pane cannot see — the writer "
            f"and reader disagree about where the store lives. Saw: {ids}"
        )
        # Every listed entry must be individually fetchable, too.
        for sid in ids:
            assert client.get(f"/api/scenarios/{sid}").status_code == 200, sid
    finally:
        client.__exit__(None, None, None)


def test_a_second_sweep_reuses_what_the_first_wrote(tmp_path: Path) -> None:
    """Staleness is read back from the same place it was written."""
    client, app = _client(tmp_path)
    try:
        overlays = client.get("/api/scenarios").json()["authored_overlays"]
        _run_sweep(client, app, overlays)
        first = {
            e["id"]: e["computed_at"]
            for e in client.get("/api/scenarios").json()["scenarios"]
        }
        assert first, "nothing was written"

        _run_sweep(client, app, overlays)
        second = {
            e["id"]: e["computed_at"]
            for e in client.get("/api/scenarios").json()["scenarios"]
        }
        assert second == first, "unchanged scenarios were re-solved instead of reused"
    finally:
        client.__exit__(None, None, None)


def test_clearing_the_cache_empties_what_the_sweep_wrote(tmp_path: Path) -> None:
    """Clear Cache must reach the same store the sweep populated."""
    client, app = _client(tmp_path)
    try:
        overlays = client.get("/api/scenarios").json()["authored_overlays"]
        _run_sweep(client, app, overlays)
        assert client.get("/api/scenarios").json()["scenarios"]

        assert client.post("/api/scenarios/clear-cache").json()["cleared"] is True
        assert client.get("/api/scenarios").json()["scenarios"] == []
    finally:
        client.__exit__(None, None, None)
