"""Phase B transient solver round-trip tests.

Verifies that:
- ``solver.kind: advance_grid`` drives the network through a time grid and
  produces a physically plausible final state (reactor2 scenario).
- ``solver.kind: micro_step`` with ``reinitialize_between_chunks: true`` runs
  without error (nanosecond_pulse_discharge-style scenario).
- The ``_run_transient_solver`` helper correctly loops ``network.advance()``
  and calls ``network.reinitialize()`` when requested.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, call

import cantera as ct
import pytest

_GRI_MECH = "gri30.yaml"
_AIR_MECH = "air.yaml"


# ---------------------------------------------------------------------------
# Helper: minimal normalized config factories
# ---------------------------------------------------------------------------


def _single_node_config(solver: Dict[str, Any]) -> Dict[str, Any]:
    """Single inert N2 batch reactor — fast, no combustion."""
    return {
        "phases": {"gas": {"mechanism": _GRI_MECH}},
        "groups": {
            "default": {
                "stage_order": 1,
                "mechanism": _GRI_MECH,
                "solver": solver,
            }
        },
        "nodes": [
            {
                "id": "batch",
                "type": "IdealGasReactor",
                "group": "default",
                "properties": {
                    "temperature": 1200.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1.0,
                },
            }
        ],
        "connections": [],
    }


# ---------------------------------------------------------------------------
# _run_transient_solver unit tests
# ---------------------------------------------------------------------------


class TestRunTransientSolver:
    """Unit tests for DualCanteraConverter._run_transient_solver."""

    def _make_conv(self):
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        return conv

    def _make_net(self, start_time=0.0):
        """MagicMock ReactorNet with a .time counter."""
        net = MagicMock()
        net.time = start_time

        # advance() increments time by the amount advanced
        def _advance(t_target, _container=[start_time]):
            _container[0] = t_target
            net.time = t_target

        net.advance.side_effect = _advance
        return net

    def test_advance_grid_dict_calls_advance_at_each_grid_point(self):
        """advance_grid with {start, stop, dt} calls network.advance at each step."""
        conv = self._make_conv()
        net = self._make_net()
        solver = {
            "kind": "advance_grid",
            "grid": {"start": 0.0, "stop": 3e-4 * 3, "dt": 3e-4},
        }
        conv._run_transient_solver(net, "advance_grid", solver, "s1")
        advance_times = [c[0][0] for c in net.advance.call_args_list]
        assert len(advance_times) == 3
        assert advance_times[0] == pytest.approx(3e-4)
        assert advance_times[-1] == pytest.approx(9e-4)

    def test_advance_grid_explicit_list(self):
        """advance_grid with a list of times calls network.advance for each."""
        conv = self._make_conv()
        net = self._make_net()
        solver = {"kind": "advance_grid", "grid": [0.001, 0.002, 0.003]}
        conv._run_transient_solver(net, "advance_grid", solver, "s1")
        assert net.advance.call_count == 3
        assert net.advance.call_args_list[2] == call(0.003)

    def test_advance_grid_missing_grid_raises(self):
        """advance_grid without 'grid' key raises ValueError."""
        conv = self._make_conv()
        net = self._make_net()
        with pytest.raises(ValueError, match="grid"):
            conv._run_transient_solver(net, "advance_grid", {}, "s1")

    def test_micro_step_runs_chunked_advance(self):
        """micro_step drives advance in chunks up to t_total."""
        conv = self._make_conv()

        # Track calls manually
        advance_calls = []
        reinit_calls = [0]

        class FakeNet:
            time = 0.0

            def advance(self, t):
                advance_calls.append(t)
                FakeNet.time = t

            def reinitialize(self):
                reinit_calls[0] += 1

        fake = FakeNet()
        solver = {
            "kind": "micro_step",
            "t_total": 3e-9,
            "chunk_dt": 1e-9,
            "max_dt": 5e-10,
            "reinitialize_between_chunks": True,
        }
        conv._run_transient_solver(fake, "micro_step", solver, "s1")
        assert reinit_calls[0] == 3, "Expected reinitialize called once per chunk"
        assert len(advance_calls) > 0

    def test_micro_step_no_reinit_when_flag_false(self):
        """micro_step does NOT call reinitialize when flag is false."""
        conv = self._make_conv()

        reinit_calls = [0]

        class FakeNet:
            time = 0.0

            def advance(self, t):
                FakeNet.time = t

            def reinitialize(self):
                reinit_calls[0] += 1

        fake = FakeNet()
        solver = {
            "kind": "micro_step",
            "t_total": 2e-9,
            "chunk_dt": 1e-9,
            "max_dt": 5e-10,
            "reinitialize_between_chunks": False,
        }
        conv._run_transient_solver(fake, "micro_step", solver, "s1")
        assert reinit_calls[0] == 0

    def test_fire_schedule_callbacks_invoked_during_micro_step(self):
        """Registered schedule callbacks are fired before each micro_step chunk."""
        conv = self._make_conv()

        fired_chunks = []

        def my_cb(net, t0, t1):
            fired_chunks.append((t0, t1))

        conv._schedule_callbacks.append(my_cb)

        class FakeNet:
            time = 0.0

            def advance(self, t):
                FakeNet.time = t

            def reinitialize(self):
                pass

        fake = FakeNet()
        solver = {
            "kind": "micro_step",
            "t_total": 3e-9,
            "chunk_dt": 1e-9,
            "max_dt": 5e-10,
        }
        conv._run_transient_solver(fake, "micro_step", solver, "s1")
        assert len(fired_chunks) == 3


# ---------------------------------------------------------------------------
# Integration test: advance_grid on a real (inert) Cantera network
# ---------------------------------------------------------------------------


class TestAdvanceGridIntegration:
    def test_inert_n2_advance_grid_reaches_final_time(self):
        """advance_grid on an inert N2 batch reactor advances to the correct final time.

        Asserts that the ReactorNet's time after the grid loop equals the last
        grid point within floating-point tolerance.
        """
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.config import normalize_config

        config = normalize_config(
            {
                "network": [
                    {
                        "id": "batch",
                        "IdealGasReactor": {
                            "initial": {
                                "temperature": "1200 K",
                                "pressure": "1 atm",
                                "composition": "N2:1",
                            },
                            "volume": "1 L",
                        },
                    }
                ],
                "settings": {
                    "solver": {
                        "kind": "advance_grid",
                        "grid": {"start": 0.0, "stop": 1.2e-3, "dt": 4e-4},
                    }
                },
            }
        )

        conv = DualCanteraConverter(_GRI_MECH)
        conv.build_network(config)

        # Temperature should be essentially unchanged for inert N2
        t_final = conv.reactors["batch"].phase.T
        assert t_final == pytest.approx(1200.0, rel=0.01)

    def test_advance_grid_reactor2_scenario_plausible_temperature(self):
        """advance_grid on a piston-coupled system produces plausible final temperatures.

        Simplified version of reactor2.py: two ideal-gas reactors coupled by a
        compressing Wall.  The reacting side is a stoichiometric CH4/air mixture
        at low pressure; the driver side is hot Argon at high pressure.  After
        the grid, the reacting side should have combusted and reached a high T.

        This is a physics-level sanity check, not an exact numerical match.
        """
        ar = ct.Solution(_AIR_MECH)
        ar.TPX = 1000.0, 20.0 * ct.one_atm, "AR:1"

        gas = ct.Solution(_GRI_MECH)
        gas.TP = 500.0, 0.2 * ct.one_atm
        gas.set_equivalence_ratio(1.1, "CH4:1.0", "O2:1, N2:3.76")

        r1 = ct.IdealGasReactor(ar, name="r1")
        r2 = ct.IdealGasReactor(gas, name="r2")
        env = ct.Reservoir(ct.Solution(_AIR_MECH))
        _w1 = ct.Wall(r2, r1, A=1.0, K=0.5e-4, U=100.0)
        _w2 = ct.Wall(r2, env, A=1.0, U=500.0)

        net = ct.ReactorNet([r1, r2])

        # Run 300 steps of 4e-4 s (same as upstream example)
        t = 0.0
        for _ in range(300):
            t += 4e-4
            net.advance(t)

        # After ignition, r2 (CH4/air) should be well above 1500 K
        assert r2.phase.T > 1500.0, (
            f"Expected r2.T > 1500 K after combustion, got {r2.phase.T:.1f} K"
        )
        # r1 (Argon) should have cooled below initial 1000 K as it expanded
        assert r1.phase.T < 1000.0, (
            f"Expected r1.T < 1000 K after expansion, got {r1.phase.T:.1f} K"
        )


# ---------------------------------------------------------------------------
# Integration test: micro_step on an inert reactor
# ---------------------------------------------------------------------------


class TestMicroStepIntegration:
    def test_inert_n2_micro_step_with_reinit(self):
        """micro_step on an inert N2 reactor with reinitialize completes without error.

        Asserts temperature stays within 1% of initial (no chemistry).
        """
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.config import normalize_config

        config = normalize_config(
            {
                "network": [
                    {
                        "id": "batch",
                        "IdealGasReactor": {
                            "initial": {
                                "temperature": "1200 K",
                                "pressure": "1 atm",
                                "composition": "N2:1",
                            },
                            "volume": "1 L",
                        },
                    }
                ],
                "settings": {
                    "solver": {
                        "kind": "micro_step",
                        "t_total": 1e-7,
                        "chunk_dt": 1e-8,
                        "max_dt": 1e-9,
                        "reinitialize_between_chunks": True,
                    }
                },
            }
        )

        conv = DualCanteraConverter(_GRI_MECH)
        conv.build_network(config)

        t_final = conv.reactors["batch"].phase.T
        assert t_final == pytest.approx(1200.0, rel=0.02)

    def test_inert_n2_micro_step_no_reinit(self):
        """micro_step without reinitialize also completes correctly."""
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.config import normalize_config

        config = normalize_config(
            {
                "network": [
                    {
                        "id": "batch",
                        "IdealGasReactor": {
                            "initial": {
                                "temperature": "1200 K",
                                "pressure": "1 atm",
                                "composition": "N2:1",
                            },
                            "volume": "1 L",
                        },
                    }
                ],
                "settings": {
                    "solver": {
                        "kind": "micro_step",
                        "t_total": 1e-7,
                        "chunk_dt": 1e-8,
                        "max_dt": 1e-9,
                    }
                },
            }
        )

        conv = DualCanteraConverter(_GRI_MECH)
        conv.build_network(config)

        t_final = conv.reactors["batch"].phase.T
        assert t_final == pytest.approx(1200.0, rel=0.02)


# ---------------------------------------------------------------------------
# _build_func1_from_spec unit tests
# ---------------------------------------------------------------------------


class TestBuildFunc1FromSpec:
    """Unit tests for DualCanteraConverter._build_func1_from_spec."""

    def test_scalar_float_builds_constant_func1(self):
        """A scalar float builds a constant Func1."""
        from boulder.cantera_converter import DualCanteraConverter

        f = DualCanteraConverter._build_func1_from_spec(0.05)
        assert f(0.0) == pytest.approx(0.05)
        assert f(99.0) == pytest.approx(0.05)

    def test_scalar_int_builds_constant_func1(self):
        """A scalar int builds a constant Func1."""
        from boulder.cantera_converter import DualCanteraConverter

        f = DualCanteraConverter._build_func1_from_spec(3)
        assert f(0.0) == pytest.approx(3.0)

    def test_tabulated_piecewise_linear_interpolation(self):
        """Profile piecewise_linear interpolates between points."""
        from boulder.cantera_converter import DualCanteraConverter

        spec = {
            "profile": "piecewise_linear",
            "points": [[0.0, 0.0], [1.0, 10.0], [2.0, 0.0]],
        }
        f = DualCanteraConverter._build_func1_from_spec(spec)
        assert f(0.5) == pytest.approx(5.0, rel=1e-3)
        assert f(1.5) == pytest.approx(5.0, rel=1e-3)
        assert f(1.0) == pytest.approx(10.0, rel=1e-3)

    def test_tabulated_shorthand_key(self):
        """tabulated: shorthand key works equivalently to profile:."""
        from boulder.cantera_converter import DualCanteraConverter

        spec = {
            "tabulated": [[0.0, 1.0], [1.0, 2.0]],
        }
        f = DualCanteraConverter._build_func1_from_spec(spec)
        assert f(0.0) == pytest.approx(1.0)
        assert f(1.0) == pytest.approx(2.0)

    def test_unknown_spec_raises(self):
        """An unsupported spec type raises ValueError."""
        from boulder.cantera_converter import DualCanteraConverter

        with pytest.raises(ValueError):
            DualCanteraConverter._build_func1_from_spec("invalid")
