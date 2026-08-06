"""Tests for cooperative simulation cancellation ("Stop Simulation").

Covers, end to end from the checkpoint up to the API:
- SolveCancelled fires at a stage boundary when the cancel token is set.
- SimulationWorker.stop_simulation() is non-blocking and, for the common
  single-stage case (no reachable checkpoint before the solve finishes),
  the finalize guard still skips the cache write and is_complete.
- stop_simulation() is a no-op on a run that already finished.
- DELETE /{sim_id} returns immediately and does not remove the registry
  entry -- that's cleanup's job once the thread has actually exited (see
  tests/test_simulation_cleanup.py for that behavior).
- The SSE stream emits a terminal "stopped" event instead of polling forever.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.api.routes.simulations import _simulations  # noqa: E402
from boulder.api.sse import simulation_event_stream  # noqa: E402
from boulder.cantera_converter import DualCanteraConverter  # noqa: E402
from boulder.config import synthesize_default_group  # noqa: E402
from boulder.simulation_worker import SimulationProgress, SimulationWorker  # noqa: E402
from boulder.staged_solver import SolveCancelled  # noqa: E402


def _make_client():
    """Return an AsyncClient bound to a fresh FastAPI app."""
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def minimal_config():
    """Return a single-stage config: no checkpoint fires before the solve completes."""
    return {
        "nodes": [
            {
                "id": "reactor1",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": 1000,
                    "pressure": 101325,
                    "composition": "CH4:1,O2:2,N2:7.52",
                },
            }
        ],
        "connections": [],
        "settings": {"end_time": 0.1, "dt": 0.05},
    }


# Minimal inert two-stage config (mirrors tests/test_staged_solver.py's
# _INERT_TWO_STAGE): pure N2, so advance_to_steady_state converges in
# milliseconds -- fast enough that setting the cancel token from stage_a's
# own completion callback reliably lands before stage_b starts.
_TWO_STAGE = {
    "groups": {
        "stage_a": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"},
        "stage_b": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"},
    },
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "nodes": [
        {
            "id": "r_a",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_a",
                "temperature": 1200.0,
                "pressure": 101325.0,
                "composition": "N2:1",
                "volume": 1e-5,
            },
        },
        {
            "id": "r_b",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_b",
                "temperature": 900.0,
                "pressure": 101325.0,
                "composition": "N2:1",
                "volume": 5e-6,
            },
        },
    ],
    "connections": [
        {
            "id": "a_to_b",
            "type": "MassFlowController",
            "source": "r_a",
            "target": "r_b",
            "properties": {"mass_flow_rate": 1e-4},
        },
    ],
}


class TestSolveCancelledCheckpoint:
    """The staged_solver.py:612 stage-boundary checkpoint."""

    def test_cancel_token_set_before_stage_b_raises_before_it_solves(self):
        """Setting the token from stage_a's own completion callback must stop stage_b.

        Proof the checkpoint sits *before* each stage's build/solve, not just
        somewhere in the loop.
        """
        conv = DualCanteraConverter(mechanism="gri30.yaml")
        cancel_token = threading.Event()
        conv.cancel_token = cancel_token

        seen_stage_ids: list[str] = []

        def _on_stage_done(stage_id: str, n_done: int, n_total: int) -> None:
            seen_stage_ids.append(stage_id)
            if stage_id == "stage_a":
                cancel_token.set()

        with pytest.raises(SolveCancelled):
            conv.build_network(_TWO_STAGE, progress_callback=_on_stage_done)

        assert seen_stage_ids == ["stage_a"]

    def test_already_set_token_stops_before_the_first_stage(self):
        conv = DualCanteraConverter(mechanism="gri30.yaml")
        conv.cancel_token = threading.Event()
        conv.cancel_token.set()

        with pytest.raises(SolveCancelled):
            conv.build_network(_TWO_STAGE)

    def test_no_token_set_solves_normally(self):
        """Absence of cancel_token (the default) must not affect a normal solve."""
        conv = DualCanteraConverter(mechanism="gri30.yaml")
        net = conv.build_network(_TWO_STAGE)
        assert net is not None


class TestSimulationWorkerStop:
    """SimulationWorker.stop_simulation() and the finalize guard."""

    def test_stop_simulation_is_non_blocking(self):
        worker = SimulationWorker()
        started = time.perf_counter()
        worker.stop_simulation()  # No worker thread at all -- must not hang.
        assert time.perf_counter() - started < 1.0

    def test_stop_simulation_noop_on_already_finished_run(self):
        """A stop request against an already-finished run must be a no-op.

        It must not retroactively mark the run as stopping.
        """
        worker = SimulationWorker()
        worker.progress = SimulationProgress(is_running=False, is_complete=True)
        worker.stop_simulation()
        assert worker.get_progress().is_stopping is False

    def test_stopped_single_stage_solve_skips_cache_and_completion(
        self, minimal_config, monkeypatch
    ):
        """Cover the common case the finalize-guard fix targets.

        A single-stage steady solve has no reachable checkpoint before it
        finishes, so SolveCancelled never fires -- only the explicit
        `_stop_event.is_set()` check in the finalize block (and in the except
        branch) makes Stop take effect here.
        """
        persist_calls = []
        monkeypatch.setattr(
            SimulationWorker,
            "_persist_to_cache",
            lambda self, *a, **k: persist_calls.append(1),
        )

        # start_simulation() expects a normalized config -- the POST route
        # calls synthesize_default_group() before constructing the worker;
        # do the same here so build_network doesn't fail for an unrelated
        # reason ("no groups section") before the stop even matters.
        config = {**minimal_config}
        synthesize_default_group(config)

        conv = DualCanteraConverter(mechanism="gri30.yaml")
        worker = SimulationWorker()
        worker.start_simulation(conv, config, 0.1, 0.05)
        worker.stop_simulation()

        for _ in range(50):
            if not worker.get_progress().is_running:
                break
            time.sleep(0.05)
        progress = worker.get_progress()

        assert progress.is_running is False
        assert progress.is_stopping is True
        assert progress.is_complete is False
        assert progress.error_message is None
        assert persist_calls == []


class TestSSEStoppedEvent:
    """boulder.api.sse.simulation_event_stream's terminal "stopped" branch."""

    class _StubWorker:
        """Replays a canned sequence of SimulationProgress snapshots."""

        def __init__(self, snapshots: list[SimulationProgress]) -> None:
            self._snapshots = snapshots
            self._i = 0

        def get_progress(self) -> SimulationProgress:
            snap = self._snapshots[min(self._i, len(self._snapshots) - 1)]
            self._i += 1
            return snap

    @pytest.mark.asyncio
    async def test_stream_emits_stopped_and_terminates(self):
        worker = self._StubWorker(
            [
                SimulationProgress(is_running=True),
                SimulationProgress(is_running=False, is_stopping=True),
            ]
        )
        events = []
        async for chunk in simulation_event_stream(worker, poll_interval=0.0):
            events.append(chunk)

        assert len(events) == 2
        assert events[0].startswith("event: progress\n")
        assert events[1].startswith("event: stopped\n")
        assert '"is_stopping": true' in events[1]

    @pytest.mark.asyncio
    async def test_stopped_takes_priority_over_a_stray_error_message(self):
        """A stopped run must never be reported as errored.

        Even if error_message happens to still carry a stale value from
        before the stop was requested.
        """
        worker = self._StubWorker(
            [
                SimulationProgress(
                    is_running=False, is_stopping=True, error_message="stale"
                ),
            ]
        )
        events = []
        async for chunk in simulation_event_stream(worker, poll_interval=0.0):
            events.append(chunk)

        assert len(events) == 1
        assert events[0].startswith("event: stopped\n")


class TestStopSimulationEndpoint:
    """DELETE /api/simulations/{sim_id} — the API-level contract."""

    @pytest.mark.asyncio
    async def test_delete_returns_immediately_and_keeps_the_registry_entry(
        self, minimal_config
    ):
        _simulations.clear()

        async with _make_client() as client:
            resp = await client.post(
                "/api/simulations",
                json={
                    "config": minimal_config,
                    "simulation_time": 0.1,
                    "time_step": 0.05,
                },
            )
            assert resp.status_code == 200
            sim_id = resp.json()["simulation_id"]
            assert sim_id in _simulations

            started = time.perf_counter()
            resp = await client.delete(f"/api/simulations/{sim_id}")
            elapsed = time.perf_counter() - started

            assert resp.status_code == 200
            assert resp.json() == {"stopping": True, "simulation_id": sim_id}
            # The old blocking behavior joined the worker thread for up to 5s;
            # this must return right away regardless of solve state.
            assert elapsed < 1.0
            # Not removed -- the SSE stream still needs to reach it.
            assert sim_id in _simulations

        _simulations.clear()

    @pytest.mark.asyncio
    async def test_delete_unknown_simulation_404s(self):
        _simulations.clear()
        async with _make_client() as client:
            resp = await client.delete("/api/simulations/does-not-exist")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_full_stop_flow_via_api_never_completes_or_caches(
        self, minimal_config, monkeypatch
    ):
        """Start, stop, and wait for exit through the real DELETE handler, not the worker directly.

        A trivial single-reactor solve can finish before this test's DELETE
        request round-trips through the ASGI transport, which would make the
        assertions below race real Cantera timing rather than test the
        guard. build_network is slowed down deterministically so the DELETE
        reliably lands first -- the point of Stop is long solves anyway.
        """
        persist_calls = []
        monkeypatch.setattr(
            SimulationWorker,
            "_persist_to_cache",
            lambda self, *a, **k: persist_calls.append(1),
        )
        original_build_network = DualCanteraConverter.build_network

        def _slow_build_network(self, *args, **kwargs):
            time.sleep(0.3)
            return original_build_network(self, *args, **kwargs)

        monkeypatch.setattr(DualCanteraConverter, "build_network", _slow_build_network)
        _simulations.clear()

        async with _make_client() as client:
            resp = await client.post(
                "/api/simulations",
                json={
                    "config": minimal_config,
                    "simulation_time": 0.1,
                    "time_step": 0.05,
                },
            )
            sim_id = resp.json()["simulation_id"]

            resp = await client.delete(f"/api/simulations/{sim_id}")
            assert resp.json()["stopping"] is True

            worker, _ = _simulations[sim_id]
            for _ in range(50):
                if not worker.get_progress().is_running:
                    break
                await asyncio.sleep(0.05)

            progress = worker.get_progress()
            assert progress.is_complete is False
            assert persist_calls == []

        _simulations.clear()
