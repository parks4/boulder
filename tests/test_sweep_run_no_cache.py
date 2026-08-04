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


class _StubConverter:
    """Records that it was actually constructed.

    Proves the sweep used `app.state.converter_class` (a host's own
    converter subclass) instead of silently falling back to plain
    `DualCanteraConverter`, which doesn't know how to resolve a host's own
    mechanism names and would fail for real (`CanteraError: findInputFile`)
    outside these mocked tests.
    """

    instances: List["_StubConverter"] = []

    def __init__(self, mechanism: Any = None, plugins: Any = None) -> None:
        # Passthrough -- a fictional resolved path would make write_payload's
        # own mechanism-file hashing fail for real; the instance count below
        # is sufficient proof this class (not DualCanteraConverter) was used.
        self.mechanism = mechanism
        _StubConverter.instances.append(self)

    def resolve_mechanism(self, name: str) -> str:
        return name


def test_sweep_run_reuses_the_cache_when_unchanged(tmp_path: Path) -> None:
    """A second run of the same config skips every scenario (fingerprint match)."""
    client, app = _client_with_config(tmp_path)
    calls: List[None] = []

    def _factory() -> _FakeWorker:
        calls.append(None)
        return _FakeWorker()

    try:
        with patch("boulder.simulation_worker.SimulationWorker", side_effect=_factory):
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
        with patch("boulder.simulation_worker.SimulationWorker", side_effect=_factory):
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
        with patch("boulder.simulation_worker.SimulationWorker", side_effect=_factory):
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


def test_sweep_run_uses_app_state_converter_class_for_mechanism_resolution(
    tmp_path: Path,
) -> None:
    """A host's own converter class must be used to resolve mechanism names.

    That class is set on `app.state` at startup by the host's CLI -- it
    must not be silently dropped in favor of plain `DualCanteraConverter`,
    which doesn't know a host's mechanism search convention and would fail
    for real (`CanteraError: findInputFile`) outside these mocks.
    """
    client, app = _client_with_config(tmp_path)
    app.state.converter_class = _StubConverter
    _StubConverter.instances.clear()

    try:
        with patch(
            "boulder.simulation_worker.SimulationWorker",
            side_effect=lambda: _FakeWorker(),
        ):
            resp = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp.status_code == 200, resp.text
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")

        # Two runs: BASELINE + "a" -- both must have gone through _StubConverter.
        assert len(_StubConverter.instances) == 2
    finally:
        _StubConverter.instances.clear()
        client.__exit__(None, None, None)


def test_sweep_run_stores_a_resolved_mechanism_not_convs_raw_attribute(
    tmp_path: Path,
) -> None:
    """`write_payload` must get a resolved mechanism, not `conv`'s raw one.

    `conv.mechanism` never updates after construction -- it stays whatever
    bare name/spec the converter was built with, even though construction
    itself resolves and loads the real one internally (see
    `DualCanteraConverter.__init__`). `write_payload`'s own `ct.Solution(...)`
    call needs a real, resolved path -- passing `conv.mechanism` straight
    through fails for real for any host whose bare mechanism names aren't
    Cantera built-ins (`CanteraError: findInputFile`).
    """

    class _PrefixResolvingConverter(_StubConverter):
        def resolve_mechanism(self, name: str) -> str:
            return f"/resolved/{name}"

    client, app = _client_with_config(tmp_path)
    app.state.converter_class = _PrefixResolvingConverter
    _StubConverter.instances.clear()
    captured_mechanisms: List[str] = []

    def _fake_write_payload(
        path: Path, gui: Any, mechanism: str, **kwargs: Any
    ) -> None:
        captured_mechanisms.append(mechanism)
        import h5py

        # One file per entry now, so just make the file exist -- the store
        # writes its own attrs on top afterwards.
        path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(str(path), "a") as handle:
            handle.attrs.setdefault("schema_version", 1)

    try:
        with (
            patch(
                "boulder.simulation_worker.SimulationWorker",
                side_effect=lambda: _FakeWorker(),
            ),
            # Patched at the source module: the sweep reaches `write_payload`
            # through `scenario_store.write_entry` now, not directly.
            patch(
                "boulder.payload_store.write_payload",
                side_effect=_fake_write_payload,
            ),
        ):
            resp = client.post("/api/sweep/run", json={"scenarios": {"a": {}}})
            assert resp.status_code == 200, resp.text
            _wait_until(lambda: app.state.sweep_job.get("status") == "done")

        assert captured_mechanisms  # BASELINE + "a" both solved (no cache yet)
        assert all(m == "/resolved/gri30.yaml" for m in captured_mechanisms)
    finally:
        _StubConverter.instances.clear()
        client.__exit__(None, None, None)
