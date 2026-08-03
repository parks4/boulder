"""The in-process sweep must fire the host's per-scenario plugin hooks.

`boulder.sweep_runner.run()` has taken `scenario_attrs` and `on_solved`
callbacks for a while, but they were *function parameters* — only reachable by
an out-of-process runner launched via `plugins.sweep_runner`. Since the GUI's
Run Sweep moved in-process it never launches that runner, so a host that
registered them silently got nothing from the button:

* `scenario_attrs` supplies the per-run KPIs the Scenario pane's Sweep Results
  plot uses as axes — without them the plot has fewer than two numeric attrs to
  choose from and hides itself entirely.
* `on_solved` is how a host persists each scenario into its own result cache so
  a later "Export" reuses the sweep's work instead of re-solving every case.

Both now live on `BoulderPlugins` and fire on the in-process path too.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

import h5py  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.cantera_converter import get_plugins  # noqa: E402
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


class _FakeWorker:
    """Completes instantly -- these tests care about hooks, not solving."""

    def __init__(self) -> None:
        self.progress = SimulationProgress(is_complete=True)

    def start_simulation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_progress(self) -> SimulationProgress:
        return self.progress


class _StubConverter:
    """Stands in for a host converter; passes mechanism names through."""

    def __init__(self, mechanism: Any = None, plugins: Any = None) -> None:
        self.mechanism = mechanism

    def resolve_mechanism(self, name: str) -> str:
        return name


def _client_with_config(tmp_path: Path):
    from boulder.runner import BoulderRunner

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG_YAML, encoding="utf-8")

    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    app.state.preloaded_raw = BoulderRunner.load(str(cfg))
    app.state.converter_class = _StubConverter
    return client, app


def _wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met within timeout")


def _run_sweep(client: TestClient, app: Any) -> None:
    def _fake_write_payload(store: Path, gui: Any, mechanism: str, **kwargs: Any):
        # Create the group the route then writes attrs onto, without needing a
        # real Cantera Solution.
        with h5py.File(str(store), "a") as handle:
            grp = kwargs.get("group")
            if grp not in handle:
                handle.create_group(grp).create_dataset("payload_json", data=b"{}")

    with (
        patch(
            "boulder.api.routes.sweep.SimulationWorker",
            side_effect=lambda: _FakeWorker(),
        ),
        patch(
            "boulder.api.routes.sweep.write_payload", side_effect=_fake_write_payload
        ),
    ):
        resp = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
        assert resp.status_code == 200, resp.text
        _wait_until(lambda: app.state.sweep_job.get("status") == "done")


def test_scenario_attrs_hook_lands_kpis_on_the_store(tmp_path: Path) -> None:
    """Returned KPIs must reach the HDF5 group -- that is what the plot reads."""
    client, app = _client_with_config(tmp_path)
    plugins = get_plugins()
    seen: List[str] = []

    def _attrs(sid: str, cfg: Dict[str, Any], gui: Dict[str, Any]) -> Dict[str, Any]:
        seen.append(sid)
        return {"t0_K": 1200.0 + len(seen), "final_X_CH4": 0.25}

    plugins.scenario_attrs = _attrs
    try:
        _run_sweep(client, app)

        assert seen == ["BASELINE", "a"]  # fires per freshly-solved scenario
        store = Path(app.state.scenario_store_path)
        with h5py.File(str(store), "r") as handle:
            for sid in ("BASELINE", "a"):
                assert "t0_K" in handle[sid].attrs, f"{sid} missing KPI attr"
                assert handle[sid].attrs["final_X_CH4"] == pytest.approx(0.25)
            # Two distinct numeric attrs across scenarios is exactly the
            # condition SweepResultsPlot needs to render at all.
            assert handle["BASELINE"].attrs["t0_K"] != handle["a"].attrs["t0_K"]
    finally:
        plugins.scenario_attrs = None
        client.__exit__(None, None, None)


def test_on_scenario_solved_hook_fires_per_scenario(tmp_path: Path) -> None:
    """The artifact hook must fire in-process, not only for a subprocess runner."""
    client, app = _client_with_config(tmp_path)
    plugins = get_plugins()
    calls: List[Tuple[str, str]] = []

    def _on_solved(sid: str, config: Any, conv: Any, sim: Any, fp: str, *rest: Any):
        calls.append((sid, fp))

    plugins.on_scenario_solved = _on_solved
    try:
        # sweep.py imports this lazily inside the hook block, so patching the
        # source module is enough -- and necessary, since building a real
        # SimulationResult needs a real converter, not `_StubConverter`.
        with patch(
            "boulder.simulation_result.make_simulation_result", return_value=object()
        ):
            _run_sweep(client, app)

        assert [sid for sid, _ in calls] == ["BASELINE", "a"]
        # Every scenario is handed the same fingerprint the store recorded, so a
        # host can key its own artifacts off it.
        store = Path(app.state.scenario_store_path)
        with h5py.File(str(store), "r") as handle:
            for sid, fp in calls:
                assert handle[sid].attrs["fingerprint"] == fp
    finally:
        plugins.on_scenario_solved = None
        client.__exit__(None, None, None)


def test_a_raising_hook_does_not_abort_the_sweep(tmp_path: Path) -> None:
    """One scenario's KPI/artifact failure must not lose the whole run."""
    client, app = _client_with_config(tmp_path)
    plugins = get_plugins()

    def _boom(*args: Any, **kwargs: Any):
        raise RuntimeError("host hook exploded")

    plugins.scenario_attrs = _boom
    plugins.on_scenario_solved = _boom
    try:
        _run_sweep(client, app)
        assert app.state.sweep_job.get("status") == "done"
        # The scenarios themselves still landed, minus the KPI attrs.
        store = Path(app.state.scenario_store_path)
        with h5py.File(str(store), "r") as handle:
            assert "BASELINE" in handle and "a" in handle
            assert "t0_K" not in handle["BASELINE"].attrs
    finally:
        plugins.scenario_attrs = None
        plugins.on_scenario_solved = None
        client.__exit__(None, None, None)
