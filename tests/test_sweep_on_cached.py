"""``on_cached`` fires for every scenario served from the store, never for a solve.

``on_solved`` is silent on a fingerprint hit, so a host that indexes runs from it
never sees a re-run of an unchanged model. ``on_cached`` is the cache-hit
counterpart: ``(scenario_id, config, fingerprint, artifacts_dir, computed_at)``.
These tests solve a real two-entry run-set on a neutral gri30 network and check
the contract on the headless sweep, the GUI sweep and the single-run cache check.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder import scenario_store  # noqa: E402
from boulder.cantera_converter import get_plugins  # noqa: E402
from boulder.config import normalize_config  # noqa: E402
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

_RUNSET_KEYS = ("scenarios", "settings")
_HOT = {"network": [{"id": "feed", "Reservoir": {"temperature": 350}}]}


@pytest.fixture
def cached_calls():
    """Register a recording ``on_scenario_cached`` plugin hook for the test."""
    plugins = get_plugins()
    calls: List[Tuple[Any, ...]] = []
    plugins.on_scenario_cached = lambda *args: calls.append(args)
    yield calls
    plugins.on_scenario_cached = None


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG_YAML, encoding="utf-8")
    return cfg


def _fingerprints(store_dir: Path) -> Dict[str, str]:
    return scenario_store.fingerprints(store_dir, identity="")


def test_headless_cached_run_fires_on_cached_once_per_scenario(
    tmp_path, cached_calls
) -> None:
    """A fresh solve fires no on_cached; the re-run fires it once per scenario.

    Each call carries the stored fingerprint, the entry's artifacts directory and
    the original ``computed_at``, not the time of the second run.
    """
    from boulder import sweep_runner

    cfg = _config(tmp_path)
    store_dir = sweep_runner.run(cfg)
    assert cached_calls == [], "a fresh solve must not fire on_cached"
    stored = _fingerprints(store_dir)
    assert len(stored) == 2
    first = {
        sid: scenario_store.entry_attrs(store_dir, sid, "")["computed_at"]
        for sid in stored
    }

    time.sleep(0.05)
    sweep_runner.run(cfg)

    assert sorted(c[0] for c in cached_calls) == sorted(stored)
    for sid, config, fingerprint, artifacts_dir, computed_at in cached_calls:
        assert fingerprint == stored[sid]
        assert isinstance(config, dict)
        assert Path(artifacts_dir) == store_artifacts_dir(store_dir, sid)
        assert computed_at == pytest.approx(first[sid])


def test_explicit_on_cached_argument_wins_and_a_raising_hook_is_logged(
    tmp_path, cached_calls, capsys
) -> None:
    """The ``run()`` argument overrides the plugin; a raising hook aborts nothing."""
    from boulder import sweep_runner

    cfg = _config(tmp_path)
    store_dir = sweep_runner.run(cfg)

    def _boom(*args: Any) -> None:
        raise RuntimeError("host hook exploded")

    sweep_runner.run(cfg, on_cached=_boom)

    assert cached_calls == [], "the explicit argument must replace the plugin hook"
    assert "on_cached hook failed" in capsys.readouterr().out
    assert len(_fingerprints(store_dir)) == 2


def test_gui_sweep_cached_rerun_fires_on_cached(tmp_path, cached_calls) -> None:
    """GUI sweep route: no call on the solve, one per scenario on the cached re-run."""
    from boulder.api.main import create_app
    from boulder.runner import BoulderRunner
    from boulder.runset import resolve_store_dir

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
        assert cached_calls == []
        store_dir = resolve_store_dir(app.state.preloaded_raw, str(cfg))
        stored = _fingerprints(store_dir)
        assert len(stored) == 2

        _run()
        assert sorted(c[0] for c in cached_calls) == sorted(stored)
        assert all(c[2] == stored[c[0]] for c in cached_calls)


def test_check_cache_hit_fires_on_cached(tmp_path, cached_calls) -> None:
    """The single-run cache check fires on a hit and stays silent on a miss."""
    from boulder import sweep_runner
    from boulder.api.main import create_app
    from boulder.runner import BoulderRunner

    # No run-set and no `settings`: the run the single-run path would key the same way.
    base = {
        k: v for k, v in yaml.safe_load(_CONFIG_YAML).items() if k not in _RUNSET_KEYS
    }
    cfg = tmp_path / "single.yaml"
    cfg.write_text(yaml.safe_dump(base), encoding="utf-8")
    store_dir = sweep_runner.run(cfg)
    stored = _fingerprints(store_dir)
    assert len(stored) == 1
    cached_calls.clear()

    def _body() -> Dict[str, Any]:
        return {
            "config": normalize_config(copy.deepcopy(base)),
            "mechanism": "gri30.yaml",
        }

    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = str(cfg)
        app.state.preloaded_raw = BoulderRunner.load(str(cfg))
        # Resolve mechanisms like the headless sweep did, whichever host is loaded.
        app.state.converter_class = get_plugins().converter_class
        hit = client.post("/api/simulations/check-cache", json=_body()).json()
        assert hit["cached"] is True, hit
        assert len(cached_calls) == 1
        sid, _cfg, fingerprint, _dir, _computed_at = cached_calls[0]
        assert fingerprint == stored[sid]

        cached_calls.clear()
        base["network"][0]["Reservoir"]["temperature"] = 999
        body = _body()
        miss = client.post("/api/simulations/check-cache", json=body).json()
        assert miss["cached"] is False
        assert cached_calls == []


def test_startup_preload_of_a_stored_result_fires_on_cached(
    tmp_path, cached_calls, monkeypatch
) -> None:
    """Opening a config whose result is stored fires on_cached once, at startup."""
    from boulder import sweep_runner

    base = {
        k: v for k, v in yaml.safe_load(_CONFIG_YAML).items() if k not in _RUNSET_KEYS
    }
    cfg = tmp_path / "single.yaml"
    cfg.write_text(yaml.safe_dump(base), encoding="utf-8")
    resolver = sweep_runner.converter_mechanism_resolver(None)
    store_dir = sweep_runner.run(cfg, resolve_mechanism=resolver)
    stored = _fingerprints(store_dir)
    assert cached_calls == []

    from boulder.api.main import create_app

    monkeypatch.setenv("BOULDER_CONFIG_PATH", str(cfg))
    with TestClient(create_app()) as client:
        client.get("/api/health")

    assert [(c[0], c[2]) for c in cached_calls] == list(stored.items())
