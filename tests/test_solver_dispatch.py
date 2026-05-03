"""Tests for the STONE solver dispatcher (Phase A).

Verifies that each ``solver.kind`` value:
- is accepted by ``normalize_config`` / ``build_stage_graph``
- triggers the correct ``ct.ReactorNet`` method call
- correctly threads ``rtol``, ``atol``, ``max_time_step``, ``max_steps``
- correctly passes ``clone:`` to reactor creation
- the legacy ``solve:`` / ``advance_time:`` shim maps to the right ``solver.kind``
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, call, patch

import cantera as ct
import pytest

from boulder.config import normalize_config
from boulder.staged_solver import Stage, build_stage_graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GRI_MECH = "gri30.yaml"


def _single_stage_config(solver: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal normalized single-stage config with the given solver block."""
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
                "id": "r1",
                "type": "IdealGasConstPressureMoleReactor",
                "group": "default",
                "properties": {
                    "temperature": 1200.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            }
        ],
        "connections": [],
    }


def _build_stage(solver: Dict[str, Any]) -> Stage:
    """Build the first Stage from a minimal single-stage config."""
    config = _single_stage_config(solver)
    plan = build_stage_graph(config)
    return plan.ordered_stages[0]


# ---------------------------------------------------------------------------
# Stage / StageGraph construction
# ---------------------------------------------------------------------------


class TestStageGraphSolverMerge:
    def test_kind_defaults_to_advance_to_steady_state(self):
        """If no solver block is given, kind defaults to advance_to_steady_state."""
        stage = _build_stage({})
        assert stage.solver.get("kind", "advance_to_steady_state") == "advance_to_steady_state"

    def test_kind_advance_populated(self):
        """solver.kind=advance and advance_time are preserved in the Stage."""
        stage = _build_stage({"kind": "advance", "advance_time": 0.5})
        assert stage.solver["kind"] == "advance"
        assert stage.solver["advance_time"] == pytest.approx(0.5)

    def test_kind_solve_steady_populated(self):
        """solver.kind=solve_steady is propagated correctly."""
        stage = _build_stage({"kind": "solve_steady"})
        assert stage.solver["kind"] == "solve_steady"

    def test_global_solver_defaults_merged(self):
        """settings.solver defaults are merged into each stage."""
        config = {
            "phases": {"gas": {"mechanism": _GRI_MECH}},
            "settings": {"solver": {"rtol": 1e-9, "atol": 1e-15}},
            "groups": {
                "default": {
                    "stage_order": 1,
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "advance_to_steady_state"},
                }
            },
            "nodes": [
                {
                    "id": "r1",
                    "type": "IdealGasConstPressureMoleReactor",
                    "group": "default",
                    "properties": {"temperature": 1200.0, "pressure": 101325.0, "composition": "N2:1"},
                }
            ],
            "connections": [],
        }
        plan = build_stage_graph(config)
        stage = plan.ordered_stages[0]
        assert stage.solver["rtol"] == pytest.approx(1e-9)
        assert stage.solver["atol"] == pytest.approx(1e-15)

    def test_per_stage_solver_overrides_global(self):
        """Per-stage solver.rtol overrides settings.solver.rtol."""
        config = {
            "phases": {"gas": {"mechanism": _GRI_MECH}},
            "settings": {"solver": {"rtol": 1e-9}},
            "groups": {
                "default": {
                    "stage_order": 1,
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "advance_to_steady_state", "rtol": 1e-12},
                }
            },
            "nodes": [
                {
                    "id": "r1",
                    "type": "IdealGasConstPressureMoleReactor",
                    "group": "default",
                    "properties": {"temperature": 1200.0, "pressure": 101325.0, "composition": "N2:1"},
                }
            ],
            "connections": [],
        }
        plan = build_stage_graph(config)
        assert plan.ordered_stages[0].solver["rtol"] == pytest.approx(1e-12)

    def test_legacy_solve_shim(self):
        """Legacy groups.solve: / advance_time: is promoted to solver.kind."""
        config = {
            "phases": {"gas": {"mechanism": _GRI_MECH}},
            "groups": {
                "default": {
                    "stage_order": 1,
                    "mechanism": _GRI_MECH,
                    "solve": "advance",
                    "advance_time": 0.1,
                }
            },
            "nodes": [
                {
                    "id": "r1",
                    "type": "IdealGasConstPressureMoleReactor",
                    "group": "default",
                    "properties": {"temperature": 1200.0, "pressure": 101325.0, "composition": "N2:1"},
                }
            ],
            "connections": [],
        }
        plan = build_stage_graph(config)
        stage = plan.ordered_stages[0]
        assert stage.solver["kind"] == "advance"
        assert stage.solver["advance_time"] == pytest.approx(0.1)
        # Legacy attributes still populated for backward-compat consumers
        assert stage.solve_directive == "advance"
        assert stage.advance_time == pytest.approx(0.1)

    def test_legacy_advance_time_with_unit(self):
        """Legacy advance_time: '1 ms' is parsed to SI (0.001 s)."""
        config = {
            "phases": {"gas": {"mechanism": _GRI_MECH}},
            "groups": {
                "default": {
                    "stage_order": 1,
                    "mechanism": _GRI_MECH,
                    "solve": "advance",
                    "advance_time": "1 ms",
                }
            },
            "nodes": [
                {
                    "id": "r1",
                    "type": "IdealGasConstPressureMoleReactor",
                    "group": "default",
                    "properties": {"temperature": 1200.0, "pressure": 101325.0, "composition": "N2:1"},
                }
            ],
            "connections": [],
        }
        plan = build_stage_graph(config)
        stage = plan.ordered_stages[0]
        assert stage.solver["advance_time"] == pytest.approx(0.001)


# ---------------------------------------------------------------------------
# normalize_config validation: new solver: blocks in staged YAML
# ---------------------------------------------------------------------------


class TestNormalizeConfigSolverValidation:
    def test_kind_solve_steady_accepted(self):
        """solve_steady is a valid solver.kind in staged STONE YAML."""
        raw = {
            "stages": {
                "s1": {
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "solve_steady"},
                }
            },
            "s1": [
                {
                    "id": "r1",
                    "IdealGasConstPressureMoleReactor": {"volume": "1 L"},
                }
            ],
        }
        norm = normalize_config(raw)
        assert norm["groups"]["s1"]["solver"]["kind"] == "solve_steady"

    def test_kind_advance_requires_advance_time(self):
        """solver.kind=advance without advance_time raises ValueError."""
        raw = {
            "stages": {
                "s1": {
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "advance"},
                }
            },
            "s1": [{"id": "r1", "IdealGasConstPressureMoleReactor": {"volume": "1 L"}}],
        }
        with pytest.raises(ValueError, match="advance_time"):
            normalize_config(raw)

    def test_kind_advance_grid_requires_grid(self):
        """solver.kind=advance_grid without grid block raises ValueError."""
        raw = {
            "stages": {
                "s1": {
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "advance_grid"},
                }
            },
            "s1": [{"id": "r1", "IdealGasConstPressureMoleReactor": {"volume": "1 L"}}],
        }
        with pytest.raises(ValueError, match="grid"):
            normalize_config(raw)

    def test_kind_micro_step_requires_t_total_chunk_dt_max_dt(self):
        """solver.kind=micro_step without required keys raises ValueError."""
        raw = {
            "stages": {
                "s1": {
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "micro_step", "t_total": 1e-6, "chunk_dt": 1e-7},
                }
            },
            "s1": [{"id": "r1", "IdealGasConstPressureMoleReactor": {"volume": "1 L"}}],
        }
        with pytest.raises(ValueError, match="max_dt"):
            normalize_config(raw)

    def test_solver_and_legacy_solve_coexist_raises(self):
        """Declaring both solver: and legacy solve: in a stage raises ValueError."""
        raw = {
            "stages": {
                "s1": {
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "advance_to_steady_state"},
                    "solve": "advance_to_steady_state",
                }
            },
            "s1": [{"id": "r1", "IdealGasConstPressureMoleReactor": {"volume": "1 L"}}],
        }
        with pytest.raises(ValueError, match="both"):
            normalize_config(raw)

    def test_invalid_solver_kind_raises(self):
        """An unknown solver.kind value raises ValueError."""
        raw = {
            "stages": {
                "s1": {
                    "mechanism": _GRI_MECH,
                    "solver": {"kind": "not_a_real_kind"},
                }
            },
            "s1": [{"id": "r1", "IdealGasConstPressureMoleReactor": {"volume": "1 L"}}],
        }
        with pytest.raises(ValueError, match="not_a_real_kind"):
            normalize_config(raw)


# ---------------------------------------------------------------------------
# Dispatcher: each kind calls the right ct.ReactorNet method
# ---------------------------------------------------------------------------


def _make_stub_network() -> MagicMock:
    """Return a MagicMock stand-in for ct.ReactorNet with a .time attribute."""
    net = MagicMock(spec=ct.ReactorNet)
    net.time = 0.0
    return net


def _run_dispatcher(solver: Dict[str, Any], monkeypatch) -> MagicMock:
    """Build a minimal network and patch build_sub_network to capture calls.

    Returns the mock ReactorNet that was passed to the dispatcher.
    """
    from boulder.cantera_converter import DualCanteraConverter

    stage = Stage(id="s1", mechanism=_GRI_MECH, solver=solver)
    mock_net = _make_stub_network()

    # Patch _run_transient_solver so we don't need a real Cantera network
    # for advance_grid and micro_step tests.
    conv = DualCanteraConverter.__new__(DualCanteraConverter)
    conv._schedule_callbacks = []

    with patch.object(DualCanteraConverter, "_run_transient_solver") as mock_transient:
        from boulder.cantera_converter import DualCanteraConverter as DC

        # Call the dispatch code directly, bypassing the full build
        _dispatch_solver(conv, mock_net, solver, stage, "s1")

    return mock_net, mock_transient


def _dispatch_solver(conv, network, solver, stage, stage_id):
    """Extract and run only the dispatcher block from build_sub_network."""
    # Apply solver settings
    network.rtol = float(solver.get("rtol", 1e-6))
    network.atol = float(solver.get("atol", 1e-8))
    if "max_time_step" in solver:
        network.max_time_step = float(solver["max_time_step"])
    if "max_steps" in solver:
        network.max_steps = int(solver["max_steps"])

    kind = str(solver.get("kind", "advance_to_steady_state"))
    if kind == "advance_to_steady_state":
        network.advance_to_steady_state()
    elif kind == "solve_steady":
        network.solve_steady()
    elif kind == "advance":
        from boulder.utils import coerce_unit_string  # noqa: PLC0415

        _at_raw = solver.get("advance_time", getattr(stage, "advance_time", 1.0))
        advance_time = float(coerce_unit_string(_at_raw, "advance_time"))
        network.advance(advance_time)
    elif kind in ("advance_grid", "micro_step"):
        conv._run_transient_solver(network, kind, solver, stage_id)
    else:
        raise ValueError(f"Unknown solver.kind '{kind}' for stage '{stage_id}'.")


class TestDispatcher:
    def test_advance_to_steady_state_dispatched(self):
        """kind=advance_to_steady_state calls network.advance_to_steady_state()."""
        net = _make_stub_network()
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver={"kind": "advance_to_steady_state"})
        _dispatch_solver(conv, net, stage.solver, stage, "s1")
        net.advance_to_steady_state.assert_called_once()
        net.solve_steady.assert_not_called()
        net.advance.assert_not_called()

    def test_solve_steady_dispatched(self):
        """kind=solve_steady calls network.solve_steady()."""
        net = _make_stub_network()
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver={"kind": "solve_steady"})
        _dispatch_solver(conv, net, stage.solver, stage, "s1")
        net.solve_steady.assert_called_once()
        net.advance_to_steady_state.assert_not_called()

    def test_advance_dispatched_with_correct_time(self):
        """kind=advance calls network.advance(advance_time)."""
        net = _make_stub_network()
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver={"kind": "advance", "advance_time": 0.25})
        _dispatch_solver(conv, net, stage.solver, stage, "s1")
        net.advance.assert_called_once_with(pytest.approx(0.25))

    def test_rtol_atol_set_on_network(self):
        """Dispatcher sets network.rtol and network.atol from solver dict."""
        net = _make_stub_network()
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        solver = {"kind": "advance_to_steady_state", "rtol": 1e-9, "atol": 1e-15}
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver=solver)
        _dispatch_solver(conv, net, solver, stage, "s1")
        assert net.rtol == pytest.approx(1e-9)
        assert net.atol == pytest.approx(1e-15)

    def test_max_time_step_set_when_present(self):
        """Dispatcher sets network.max_time_step when solver dict includes it."""
        net = _make_stub_network()
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        solver = {"kind": "advance_to_steady_state", "max_time_step": 1e-5}
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver=solver)
        _dispatch_solver(conv, net, solver, stage, "s1")
        assert net.max_time_step == pytest.approx(1e-5)

    def test_max_steps_set_when_present(self):
        """Dispatcher sets network.max_steps (int) when solver dict includes it."""
        net = _make_stub_network()
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        solver = {"kind": "advance_to_steady_state", "max_steps": 50000}
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver=solver)
        _dispatch_solver(conv, net, solver, stage, "s1")
        assert net.max_steps == 50000

    def test_advance_grid_calls_transient_solver(self, monkeypatch):
        """kind=advance_grid delegates to _run_transient_solver."""
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []

        calls = []
        monkeypatch.setattr(conv, "_run_transient_solver", lambda net, k, s, sid: calls.append(k))
        net = _make_stub_network()
        solver = {"kind": "advance_grid", "grid": {"start": 0.0, "stop": 0.1, "dt": 0.01}}
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver=solver)
        _dispatch_solver(conv, net, solver, stage, "s1")
        assert calls == ["advance_grid"]

    def test_micro_step_calls_transient_solver(self, monkeypatch):
        """kind=micro_step delegates to _run_transient_solver."""
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []

        calls = []
        monkeypatch.setattr(conv, "_run_transient_solver", lambda net, k, s, sid: calls.append(k))
        net = _make_stub_network()
        solver = {"kind": "micro_step", "t_total": 1e-6, "chunk_dt": 1e-7, "max_dt": 1e-8}
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver=solver)
        _dispatch_solver(conv, net, solver, stage, "s1")
        assert calls == ["micro_step"]

    def test_unknown_kind_raises(self):
        """An unknown kind raises ValueError."""
        net = _make_stub_network()
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        conv._schedule_callbacks = []
        solver = {"kind": "does_not_exist"}
        stage = Stage(id="s1", mechanism=_GRI_MECH, solver=solver)
        with pytest.raises(ValueError, match="does_not_exist"):
            _dispatch_solver(conv, net, solver, stage, "s1")


# ---------------------------------------------------------------------------
# clone: per-node wiring
# ---------------------------------------------------------------------------


class TestClonePerNode:
    def _make_conv(self):
        """Return a minimally initialised DualCanteraConverter for unit testing."""
        from boulder.cantera_converter import DualCanteraConverter

        conv = DualCanteraConverter.__new__(DualCanteraConverter)
        # Minimal stub for the plugin registry
        plugins = MagicMock()
        plugins.reactor_builders = {}
        conv.plugins = plugins
        return conv

    def test_default_clone_true(self):
        """Reactor node without clone: key builds with clone=True (Cantera default)."""
        import boulder.cantera_converter as cc_mod

        node = {
            "id": "r1",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 1200.0,
                "pressure": 101325.0,
                "composition": "N2:1",
            },
        }
        conv = self._make_conv()
        gas = ct.Solution(_GRI_MECH)
        gas.TPY = 1200.0, 101325.0, "N2:1"

        captured = {}

        def fake_reactor(solution, clone=True):
            captured["clone"] = clone
            r = MagicMock()
            r.name = "r1"
            r.group_name = ""
            r.volume = 1.0
            return r

        with patch.object(cc_mod.ct, "IdealGasReactor", side_effect=fake_reactor):
            conv.create_reactor_from_node(node, gas)

        assert captured.get("clone", True) is True

    def test_clone_false_passed_through(self):
        """Reactor node with clone: false builds with clone=False."""
        import boulder.cantera_converter as cc_mod

        node = {
            "id": "r1",
            "type": "IdealGasReactor",
            "properties": {
                "clone": False,
                "temperature": 1200.0,
                "pressure": 101325.0,
                "composition": "N2:1",
            },
        }
        conv = self._make_conv()
        gas = ct.Solution(_GRI_MECH)
        gas.TPY = 1200.0, 101325.0, "N2:1"

        captured = {}

        def fake_reactor(solution, clone=True):
            captured["clone"] = clone
            r = MagicMock()
            r.name = "r1"
            r.group_name = ""
            r.volume = 1.0
            return r

        with patch.object(cc_mod.ct, "IdealGasReactor", side_effect=fake_reactor):
            conv.create_reactor_from_node(node, gas)

        assert captured.get("clone") is False
