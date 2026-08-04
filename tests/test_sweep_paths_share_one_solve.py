"""The GUI and CLI sweeps must solve a scenario through the same code.

They already shared the scaffolding (`expand_scenarios`, `prepare_scenario`,
`write_payload`) and even the same converter methods, but
each assembled the stored `gui` payload itself — ~15 keys, hand-built twice.
They had drifted: `updated_nodes` / `updated_connections` carried the real
build-time additions on the GUI path and were hard-coded `None` on the CLI one.

Those fields are how the frontend learns about nodes a *staged* solve
synthesises during build (interface reservoirs) and edges added by post-build
hooks. So the same scenario drew a different network graph depending on which
button produced it.

Both now go through `sweep_runner.solve_scenario`, which builds the payload via
`gui_payload_from_progress`. These tests pin that.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List

import pytest

from boulder import sweep_runner  # noqa: E402
from boulder.simulation_worker import SimulationProgress  # noqa: E402


def test_gui_route_does_not_build_its_own_payload() -> None:
    """The route must delegate, not hand-assemble a second payload dict.

    A structural check on purpose: the bug this guards against is someone
    reintroducing a parallel builder, which no behavioural assertion in a
    mocked test would notice until the two silently diverged again.
    """
    from boulder.api.routes import sweep as sweep_route

    src = inspect.getsource(sweep_route)
    assert "solve_scenario(" in src, "GUI route no longer calls the shared solve"
    # The payload's distinctive keys should appear only in the shared builder.
    for key in ('"reactors_series"', '"sankey_links"', '"updated_connections"'):
        assert key not in src, (
            f"{key} is assembled in the GUI route again -- payload construction "
            "belongs solely in sweep_runner.gui_payload_from_progress"
        )


def test_payload_carries_build_time_nodes_not_none() -> None:
    """`updated_nodes` must survive into the payload -- the field that drifted."""
    progress = SimulationProgress(is_complete=True)
    progress.updated_nodes = [{"id": "interface_reservoir"}]
    progress.updated_connections = [{"id": "synthesized_edge"}]

    payload = sweep_runner.gui_payload_from_progress(progress, started=0.0)

    assert payload["updated_nodes"] == [{"id": "interface_reservoir"}]
    assert payload["updated_connections"] == [{"id": "synthesized_edge"}]
    assert payload["status"] == "complete"
    assert payload["is_complete"] is True


def test_solver_window_is_shared_and_defaults_consistently() -> None:
    """Both paths must agree on how long a scenario runs."""
    assert sweep_runner.solver_window({"settings": {"end_time": 4.0, "dt": 0.5}}) == (
        4.0,
        0.5,
    )
    # dt defaults to a tenth of the window, not to some path-specific constant.
    assert sweep_runner.solver_window({"settings": {"end_time": 2.0}}) == (2.0, 0.2)
    # No end_time at all -> the documented 1 s fallback, same on both paths.
    assert sweep_runner.solver_window({}) == (1.0, 0.1)


def test_solve_scenario_honours_an_explicit_converter_class() -> None:
    """The GUI passes `app.state.converter_class`; it must win.

    Regression guard for parks4/boulder#135: resolving mechanisms through the
    entry-point plugin registry instead of the class the CLI registered at
    startup is what made a host's own mechanism names unresolvable.
    """
    built: List[Any] = []

    class _Marker:
        def __init__(self, mechanism: Any = None, plugins: Any = None) -> None:
            self.mechanism = mechanism
            built.append(self)

        def resolve_mechanism(self, name: str) -> str:
            return name

    class _FakeWorker:
        def __init__(self) -> None:
            self.progress = SimulationProgress(is_complete=True)

        def start_simulation(self, *a: Any, **k: Any) -> None:
            pass

        def get_progress(self) -> SimulationProgress:
            return self.progress

    from unittest.mock import patch

    config: Dict[str, Any] = {"settings": {"end_time": 1.0}}
    with patch(
        "boulder.simulation_worker.SimulationWorker", side_effect=lambda: _FakeWorker()
    ):
        _gui, mech, conv = sweep_runner.solve_scenario(
            config, "gri30.yaml", converter_cls=_Marker
        )

    assert len(built) == 1, "the explicit converter class was not used"
    assert isinstance(conv, _Marker)
    assert mech == "gri30.yaml"


def test_progress_callback_receives_polls_during_the_solve() -> None:
    """The GUI's per-stage progress depends on this callback firing."""
    seen: List[SimulationProgress] = []

    class _StagedWorker:
        """Reports one incomplete staged poll, then completes."""

        def __init__(self) -> None:
            self._polls = 0

        def start_simulation(self, *a: Any, **k: Any) -> None:
            pass

        def get_progress(self) -> SimulationProgress:
            self._polls += 1
            p = SimulationProgress(is_complete=self._polls > 1)
            p.n_stages = 3
            p.stages_done = min(self._polls, 3)
            return p

    class _Conv:
        def __init__(self, mechanism: Any = None, plugins: Any = None) -> None:
            self.mechanism = mechanism

    from unittest.mock import patch

    with patch(
        "boulder.simulation_worker.SimulationWorker",
        side_effect=lambda: _StagedWorker(),
    ):
        sweep_runner.solve_scenario(
            {"settings": {"end_time": 1.0}},
            "gri30.yaml",
            converter_cls=_Conv,
            progress_cb=seen.append,
            poll_interval=0.0,
        )

    assert len(seen) >= 2, "callback should fire while solving, not just at the end"
    assert seen[0].n_stages == 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
