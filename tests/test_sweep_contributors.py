"""Cache contributors run for every freshly solved sweep entry, GUI and headless.

A single GUI run called ``run_contributors`` after its solve, but the shared
sweep tail (``sweep_runner.store_solved_scenario``) did not, so a host had to
call it from ``on_scenario_solved`` -- a hook that gets neither the store nor
the artifacts directory. These tests solve a real two-point sweep on a neutral
gri30 network and check the contributor contract on both sweep entry points.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder import result_cache  # noqa: E402
from boulder.runset import store_artifacts_dir  # noqa: E402

_CONFIG_YAML = """\
phases:
  gas:
    mechanism: gri30.yaml
settings:
  end_time: 0.01
  dt: 0.005
network:
  - id: feed
    Reservoir:
      temperature: 300
      pressure: 101325
      composition: "N2:1"
  - id: reactor
    IdealGasReactor:
      volume: 1.0
      initial:
        temperature: 300
        pressure: 101325
        composition: "N2:1"
  - id: outlet
    Reservoir:
      temperature: 300
      pressure: 101325
      composition: "N2:1"
  - id: inlet
    MassFlowController:
      mass_flow_rate: 0.01
    source: feed
    target: reactor
  - id: valve
    Valve:
      valve_coeff: 1.0
    source: reactor
    target: outlet
scenarios:
  hot:
    network:
      - id: feed
        Reservoir:
          temperature: 350
"""
# Two entries, BASELINE and hot. Their ids need no sanitising, so the cache
# lookup by id finds them on the second run.


_HOT = {"network": [{"id": "feed", "Reservoir": {"temperature": 350}}]}


class _Recorder(result_cache.CacheContributorPlugin):
    """Records each call; optionally raises, to prove the entry survives."""

    def __init__(self, raises: bool = False) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.raises = raises

    @property
    def contributor_id(self) -> str:
        return "test_recorder"

    def contribute(
        self, config, converter, simulation_result, fingerprint, artifacts_dir
    ):
        self.calls.append(
            {
                "fingerprint": fingerprint,
                "artifacts_dir": Path(artifacts_dir),
                "result": simulation_result,
            }
        )
        if self.raises:
            raise RuntimeError("contributor failure")


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch):
    """Register a fresh recorder in the global contributor registry."""

    def _make(raises: bool = False) -> _Recorder:
        rec = _Recorder(raises=raises)
        monkeypatch.setattr(
            result_cache._cache_contributor_registry, "contributors", [rec]
        )
        return rec

    return _make


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG_YAML, encoding="utf-8")
    return cfg


def _call_dirs(rec: _Recorder) -> List[Path]:
    return sorted(c["artifacts_dir"] for c in rec.calls)


def test_headless_sweep_runs_contributors_once_per_entry(tmp_path, recorder) -> None:
    """Headless sweep calls each contributor once per solved entry.

    The call gets that entry's artifacts directory and a SimulationResult; a
    second run (all cache hits) calls nothing.
    """
    from boulder import scenario_store, sweep_runner

    rec = recorder()
    cfg = _config(tmp_path)

    store_dir = sweep_runner.run(cfg)

    ids = [e["id"] for e in scenario_store.list_entries(store_dir, identity="")]
    assert len(ids) == 2
    assert _call_dirs(rec) == sorted(store_artifacts_dir(store_dir, sid) for sid in ids)
    assert len({c["fingerprint"] for c in rec.calls}) == 2
    assert all(c["result"] is not None for c in rec.calls)

    rec.calls.clear()
    sweep_runner.run(cfg)
    assert rec.calls == [], "a cache hit must not run contributors"


def test_failing_contributor_does_not_lose_the_entry(tmp_path, recorder) -> None:
    """A contributor that raises must not stop the sweep or drop its entries."""
    from boulder import scenario_store, sweep_runner

    rec = recorder(raises=True)

    store_dir = sweep_runner.run(_config(tmp_path))

    assert len(rec.calls) == 2
    assert len(scenario_store.list_entries(store_dir, identity="")) == 2


def test_gui_sweep_runs_contributors_once_per_entry(tmp_path, recorder) -> None:
    """GUI sweep route: same contract as headless, and cache hits run nothing."""
    from boulder import scenario_store
    from boulder.api.main import create_app
    from boulder.runner import BoulderRunner
    from boulder.runset import resolve_store_dir

    rec = recorder()
    cfg = _config(tmp_path)
    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = str(cfg)
        app.state.preloaded_raw = BoulderRunner.load(str(cfg))

        def _run() -> None:
            resp = client.post("/api/sweep/run", json={"scenarios": {"hot": _HOT}})
            assert resp.status_code == 200, resp.text
            deadline = time.time() + 120
            while app.state.sweep_job.get("status") not in ("done", "error"):
                assert time.time() < deadline, "sweep did not finish"
                time.sleep(0.05)
            assert app.state.sweep_job.get("status") == "done", app.state.sweep_job

        _run()
        store_dir = resolve_store_dir(app.state.preloaded_raw, str(cfg))
        assert store_dir is not None
        ids = [e["id"] for e in scenario_store.list_entries(store_dir, identity="")]
        assert len(ids) == 2
        assert _call_dirs(rec) == sorted(
            store_artifacts_dir(store_dir, sid) for sid in ids
        )

        rec.calls.clear()
        _run()
        assert rec.calls == [], "a cache hit must not run contributors"
