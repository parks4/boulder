"""Sequential run-sets: ``scenarios_sweep.for`` / ``.while`` and the legacy-key rename.

The declarative loop used to handle only *independent* points (grid axes and
``scenarios:`` overlays). Anything that had to be solved in order -- each point
warm-started from the last, or a chain whose length is only known once a
condition trips -- needed a hand-written ``sweep.runner`` that bypassed the
converter, so the network it solved was not the one the YAML declared. These
tests pin the two chain forms that replace it, the warm start behind
``initial: from_previous``, and the rename of ``sweep:``/``sweeps:`` to
``scenarios_sweep:``.
"""

from __future__ import annotations

import ast
import copy
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from boulder import runset as runset_module
from boulder.runset import (
    RUN_SET_KEY,
    RunSetCursor,
    apply_previous_state,
    canonicalize_run_set_keys,
    iter_run_set,
    result_value_at,
    run_set_size,
    sequential_of,
    sweeps_of,
)

_TANK_T = "network[id=tank].Reservoir.temperature"
_REACTOR_T = "network[id=reactor].IdealGasMoleReactor.initial.temperature"
_TAU = "network[id=mfc].MassFlowController.tau_s"


def _base_config() -> Dict[str, Any]:
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "network": [
            {
                "id": "tank",
                "Reservoir": {
                    "temperature": 925.0,
                    "pressure": 101325.0,
                    "composition": "CH4:0.095,O2:0.21,N2:0.695",
                },
            },
            {
                "id": "reactor",
                "IdealGasMoleReactor": {
                    "volume": 3.05e-05,
                    "energy": "off",
                    "initial": {
                        "temperature": 925.0,
                        "pressure": 101325.0,
                        "composition": "CH4:0.095,O2:0.21,N2:0.695",
                    },
                },
            },
            {
                "id": "mfc",
                "MassFlowController": {"closure": "residence_time", "tau_s": 0.1},
                "source": "tank",
                "target": "reactor",
            },
        ],
    }


def _for_config(initial: str = "from_previous") -> Dict[str, Any]:
    raw = _base_config()
    raw[RUN_SET_KEY] = {
        "for": {
            "parameter": [_TANK_T, _REACTOR_T],
            "values": [650, 700],
            "initial": initial,
        }
    }
    return raw


def _while_config(**overrides: Any) -> Dict[str, Any]:
    raw = _base_config()
    spec: Dict[str, Any] = {
        "parameter": _TAU,
        "condition": {"path": "network[id=reactor].T", "gt": 500},
        "update": {"multiply": 0.9},
        "max_iters": 10,
        "initial": "from_previous",
    }
    spec.update(overrides)
    raw[RUN_SET_KEY] = {"while": spec}
    return raw


def _node(cfg: Dict[str, Any], nid: str) -> Dict[str, Any]:
    return next(n for n in cfg["network"] if n["id"] == nid)


def _states(T: float, X: Dict[str, float] | None = None) -> Dict[str, Dict[str, Any]]:
    return {"reactor": {"T": T, "P": 2.0e5, "X": X or {"CH4": 0.5, "N2": 0.5}}}


# ---------------------------------------------------------------------------
# Legacy keys
# ---------------------------------------------------------------------------


def test_legacy_sweep_key_is_renamed_with_a_warning() -> None:
    raw = {"sweep": {"T": {"path": _TANK_T, "values": [1, 2]}}}
    # Patch the module logger rather than rely on caplog: another test in the
    # suite may have reconfigured the "boulder" logger (handlers/propagation),
    # which would silently hide the record from caplog.
    with patch.object(runset_module.logger, "warning") as warn:
        found = canonicalize_run_set_keys(raw)
    assert found == ["sweep"]
    assert "sweep" not in raw
    assert raw[RUN_SET_KEY] == {"T": {"path": _TANK_T, "values": [1, 2]}}
    assert warn.call_count == 1
    assert RUN_SET_KEY in " ".join(str(a) for a in warn.call_args.args), (
        "the warning must name the replacement key"
    )


def test_legacy_key_is_still_read_silently_by_the_accessors() -> None:
    """Accessors tolerate a not-yet-canonicalized dict; the warning belongs to load time."""
    raw = {"sweeps": {"T": {"path": _TANK_T, "values": [1, 2]}}}
    assert sweeps_of(raw) == {"T": {"path": _TANK_T, "values": [1, 2]}}


def test_continuation_block_is_kept_but_warned() -> None:
    raw = {"continuation": {"parameter": "connections.mfc.mass_flow_rate"}}
    with patch.object(runset_module.logger, "warning") as warn:
        found = canonicalize_run_set_keys(raw)
    assert found == ["continuation"]
    assert "continuation" in raw, "still consumed by BoulderRunner.run_continuation"
    assert warn.call_count == 1
    assert "while" in " ".join(str(a) for a in warn.call_args.args), (
        "the warning must point at the scenarios_sweep.while form"
    )


def test_normalize_config_renames_the_legacy_key() -> None:
    from boulder.config import normalize_config

    raw = _base_config()
    raw["sweep"] = {"T": {"path": _TANK_T, "values": [300, 400]}}
    normalized = normalize_config(raw)
    assert "sweep" not in normalized
    assert normalized[RUN_SET_KEY] == {"T": {"path": _TANK_T, "values": [300, 400]}}


# ---------------------------------------------------------------------------
# for:
# ---------------------------------------------------------------------------


def test_for_chain_walks_the_values_in_order_and_records_the_sweep_point() -> None:
    points = list(iter_run_set(_for_config(), RunSetCursor(), symbols={}))
    assert [sid for sid, _ in points] == [
        "BASELINE__temperature=650",
        "BASELINE__temperature=700",
    ]
    first = points[0][1]
    assert _node(first, "tank")["Reservoir"]["temperature"] == 650
    assert (
        _node(first, "reactor")["IdealGasMoleReactor"]["initial"]["temperature"] == 650
    )
    assert first["metadata"]["sweep_point"] == {"temperature": 650}
    assert RUN_SET_KEY not in first, "the directive is stripped from every point"


def test_for_chain_from_previous_seeds_initial_but_the_parameter_wins() -> None:
    cursor = RunSetCursor()
    it = iter_run_set(_for_config(), cursor, symbols={})
    _sid, first = next(it)
    # Step 0 has no previous step: the composition is the one written in the YAML.
    assert (
        _node(first, "reactor")["IdealGasMoleReactor"]["initial"]["composition"]
        == "CH4:0.095,O2:0.21,N2:0.695"
    )

    # The loop records the converged state before asking for the next point.
    cursor.previous_states = _states(T=1234.0)
    _sid, second = next(it)
    initial = _node(second, "reactor")["IdealGasMoleReactor"]["initial"]
    assert initial["composition"] == "CH4:0.5,N2:0.5", "converged composition carried"
    assert initial["pressure"] == 2.0e5, "converged pressure carried"
    assert initial["temperature"] == 700, "the swept parameter wins over the carried T"
    # Boundary conditions are never touched by a warm start.
    assert (
        _node(second, "tank")["Reservoir"]["composition"]
        == "CH4:0.095,O2:0.21,N2:0.695"
    )
    assert _node(second, "tank")["Reservoir"]["temperature"] == 700


def test_for_chain_from_config_ignores_the_previous_state() -> None:
    cursor = RunSetCursor()
    it = iter_run_set(_for_config(initial="from_config"), cursor, symbols={})
    next(it)
    cursor.previous_states = _states(T=1234.0)
    _sid, second = next(it)
    initial = _node(second, "reactor")["IdealGasMoleReactor"]["initial"]
    assert initial["composition"] == "CH4:0.095,O2:0.21,N2:0.695"
    assert initial["pressure"] == 101325.0


def test_apply_previous_state_respects_a_top_level_operating_pressure() -> None:
    cfg = _base_config()
    cfg["network"].append(
        {
            "id": "psr",
            "IdealGasConstPressureReactor": {"pressure": 5.0e5, "initial": {}},
        }
    )
    seeded = apply_previous_state(
        cfg, {"psr": {"T": 900.0, "P": 4.9e5, "X": {"N2": 1.0}}}
    )
    assert seeded == ["psr"]
    initial = _node(cfg, "psr")["IdealGasConstPressureReactor"]["initial"]
    assert initial == {"temperature": 900.0, "composition": "N2:1"}, (
        "pressure is an operating constraint here, not state to carry"
    )


# ---------------------------------------------------------------------------
# while:
# ---------------------------------------------------------------------------


def test_while_chain_starts_from_the_config_value_updates_and_stops_on_the_condition() -> (
    None
):
    cursor = RunSetCursor()
    seen: List[str] = []
    temperatures = iter([1500.0, 1400.0, 300.0])
    for sid, cfg in iter_run_set(_while_config(), cursor, symbols={}):
        seen.append(sid)
        assert RUN_SET_KEY not in cfg
        # The solve loop's job: record the converged state of the point just solved.
        cursor.previous_states = _states(T=next(temperatures))
    # 0.1 (as written), then *0.9 twice; the point that extinguished (T=300) is
    # recorded, and the re-test on it ends the chain -- like the Python loop.
    assert seen == [
        "BASELINE__tau_s=0.1",
        "BASELINE__tau_s=0.09",
        "BASELINE__tau_s=0.081",
    ]


def test_while_chain_respects_max_iters() -> None:
    cursor = RunSetCursor()
    count = 0
    for _sid, _cfg in iter_run_set(_while_config(max_iters=3), cursor, symbols={}):
        count += 1
        cursor.previous_states = _states(T=1500.0)  # never trips
    assert count == 3


def test_while_chain_needs_a_previous_state_to_evaluate_its_condition() -> None:
    it = iter_run_set(_while_config(), RunSetCursor(), symbols={})
    next(it)
    with pytest.raises(ValueError, match="no reactor state"):
        next(it)


def test_result_value_at_reads_T_P_and_species() -> None:
    states = {"r": {"T": 1200.0, "P": 3.0e5, "X": {"CO": 0.02}, "Y": {"CO": 0.03}}}
    assert result_value_at(states, "network[id=r].T") == 1200.0
    assert result_value_at(states, "network[id=r].P") == 3.0e5
    assert result_value_at(states, "network[id=r].X.CO") == 0.02
    assert result_value_at(states, "network[id=r].Y.CO") == 0.03
    with pytest.raises(ValueError, match="no reactor 'zz'"):
        result_value_at(states, "network[id=zz].T")
    with pytest.raises(ValueError, match="species 'H2'"):
        result_value_at(states, "network[id=r].X.H2")


# ---------------------------------------------------------------------------
# Validation and sizing
# ---------------------------------------------------------------------------


def test_a_chain_cannot_share_its_block_with_grid_axes() -> None:
    raw = _while_config()
    raw[RUN_SET_KEY]["T"] = {"path": _TANK_T, "values": [1, 2]}
    with pytest.raises(ValueError, match="grid axes"):
        sequential_of(raw, symbols={})


def test_for_and_while_together_is_rejected() -> None:
    raw = _while_config()
    raw[RUN_SET_KEY]["for"] = {"parameter": _TANK_T, "values": [1]}
    with pytest.raises(ValueError, match="not both"):
        sequential_of(raw, symbols={})


@pytest.mark.parametrize(
    "override, match",
    [
        (
            {"condition": {"path": "network[id=reactor].T"}},
            "exactly one of gt/ge/lt/le",
        ),
        (
            {"condition": {"path": "network[id=reactor].T", "gt": 500, "lt": 1}},
            "exactly one",
        ),
        ({"update": {"multiply": 0.9, "add": 1}}, "exactly one of multiply/add/set"),
        ({"update": "0.9"}, "update must be"),
        ({"initial": "from_nowhere"}, "initial must be"),
        ({"max_iters": 0}, "positive integer"),
        ({"parameter": None}, "parameter must be"),
    ],
)
def test_malformed_while_chains_fail_loudly(
    override: Dict[str, Any], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        sequential_of(_while_config(**override), symbols={})


def test_run_set_size_counts_for_values_but_not_an_open_ended_while() -> None:
    assert run_set_size(_for_config()) == 2
    assert run_set_size(_while_config()) == 0, (
        "length only known once the condition trips"
    )


def test_a_chain_with_scenarios_keeps_the_baseline_and_the_overlays() -> None:
    raw = _for_config()
    raw["scenarios"] = {"hot": {"metadata": {"description": "hotter"}}}
    labels = [sid for sid, _ in iter_run_set(raw, RunSetCursor(), symbols={})]
    assert labels == [
        "BASELINE",
        "hot",
        "BASELINE__temperature=650",
        "BASELINE__temperature=700",
    ]


# ---------------------------------------------------------------------------
# sim2stone: the detected extinction loop is emitted as a scenarios_sweep.while
# ---------------------------------------------------------------------------


def test_detect_continuation_records_the_tested_reactor_variable() -> None:
    from boulder.sim2stone_ast import _detect_continuation

    src = (
        "while combustor.T > 500:\n    sim.solve_steady()\n    residence_time *= 0.9\n"
    )
    cont = _detect_continuation(ast.parse(src))
    assert cont is not None
    assert cont.condition_var == "combustor"
    assert (cont.tau_var, cont.tau_factor, cont.condition_attr) == (
        "residence_time",
        0.9,
        "T",
    )


def test_extinction_loop_is_emitted_as_a_while_chain_on_real_stone_paths() -> None:
    from boulder.sim2stone import _build_scenarios_sweep_block
    from boulder.sim2stone_ast import (
        ASTExtractionResult,
        DetectedClosure,
        DetectedContinuation,
    )

    closure = DetectedClosure(
        mfc_var="inlet_mfc", reactor_var="combustor", tau_var="residence_time"
    )
    result = ASTExtractionResult(
        closures=[closure],
        continuations=[
            DetectedContinuation(
                tau_var="residence_time",
                tau_factor=0.9,
                condition_attr="T",
                condition_threshold=500.0,
                condition_var="combustor",
            )
        ],
    )
    block = _build_scenarios_sweep_block(
        result,
        ["inlet", "combustor", "exhaust"],
        {"air_inlet": closure},
        {"air_inlet": "combustor"},
    )
    assert block is not None
    block.pop("_derived_via")
    assert block == {
        "while": {
            "parameter": "network[id=air_inlet].MassFlowController.tau_s",
            "condition": {"path": "network[id=combustor].T", "gt": 500.0},
            "update": {"multiply": 0.9},
            "max_iters": 200,
            "initial": "from_previous",
        }
    }
    # `initial:` closes the block, `parameter:` opens it -- the documented order.
    assert list(block["while"]) == [
        "parameter",
        "condition",
        "update",
        "max_iters",
        "initial",
    ]


def test_a_loop_whose_tau_matches_no_mfc_closure_emits_nothing() -> None:
    from boulder.sim2stone import _build_scenarios_sweep_block
    from boulder.sim2stone_ast import ASTExtractionResult, DetectedContinuation

    result = ASTExtractionResult(
        continuations=[DetectedContinuation("tau", 0.9, "T", 500.0, condition_var="r")]
    )
    assert _build_scenarios_sweep_block(result, ["r"], {}, {}) is None


# ---------------------------------------------------------------------------
# End to end: Run Sweep executes a while: chain through the ordinary solve loop
# ---------------------------------------------------------------------------

_CHAIN_YAML = """\
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: solve_steady
network:
- id: inlet
  Reservoir:
    temperature: 300 K
    pressure: 101325 Pa
    composition: "CH4:1"
- id: combustor
  IdealGasReactor:
    volume: 1.0
    initial:
      temperature: 1500 K
      pressure: 101325 Pa
      composition: "N2:1"
- id: exhaust
  Reservoir:
    temperature: 300 K
    pressure: 101325 Pa
    composition: "N2:1"
- id: air_inlet
  MassFlowController:
    closure: residence_time
    tau_s: 0.1
  source: inlet
  target: combustor
- id: outlet_pc
  PressureController:
    master: air_inlet
    pressure_coeff: 0.01
  source: combustor
  target: exhaust
scenarios_sweep:
  while:
    parameter: network[id=air_inlet].MassFlowController.tau_s
    condition: {path: "network[id=combustor].T", gt: 500}
    update: {multiply: 0.9}
    max_iters: 10
    initial: from_previous
"""


def _tau_of(config: Dict[str, Any]) -> float:
    conn = next(c for c in config["connections"] if c["id"] == "air_inlet")
    props = conn.get("properties") or conn
    return float(props["tau_s"])


def test_run_sweep_executes_a_while_chain_point_by_point(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("h5py")
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from boulder import scenario_store
    from boulder.api.main import create_app
    from boulder.runner import BoulderRunner
    from boulder.runset import resolve_store_dir
    from boulder.simulation_worker import SimulationProgress

    cooling = iter([1500.0, 1200.0, 300.0])
    solved: List[Dict[str, Any]] = []

    class _CoolingWorker:
        """Completes instantly; each solve reports the combustor a step cooler."""

        def __init__(self) -> None:
            self.progress = SimulationProgress(is_complete=True)
            self.progress.times = [0.0]
            self.progress.reactors_series = {
                "combustor": {
                    "T": [next(cooling)],
                    "P": [101325.0],
                    "X": {"N2": [0.7], "O2": [0.3]},
                }
            }

        def start_simulation(self, conv: Any, config: Dict[str, Any], *a: Any) -> None:
            solved.append(copy.deepcopy(config))

        def get_progress(self) -> SimulationProgress:
            return self.progress

    class _StubConverter:
        def __init__(self, mechanism: Any = None, plugins: Any = None) -> None:
            self.mechanism = mechanism

        def resolve_mechanism(self, name: str) -> str:
            return name

    cfg = tmp_path / "chain.yaml"
    cfg.write_text(_CHAIN_YAML, encoding="utf-8")
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        app.state.preloaded_config_path = str(cfg)
        app.state.preloaded_raw = BoulderRunner.load(str(cfg))
        app.state.converter_class = _StubConverter

        info = client.get("/api/sweep").json()
        assert info["can_run"] is True
        assert info["n_scenarios"] == 0, "an open-ended chain has no count up front"

        with patch(
            "boulder.simulation_worker.SimulationWorker",
            side_effect=lambda: _CoolingWorker(),
        ):
            resp = client.post("/api/sweep/run", json={})
            assert resp.status_code == 200, resp.text
            deadline = time.time() + 30.0
            while time.time() < deadline:
                if app.state.sweep_job.get("status") in ("done", "error"):
                    break
                time.sleep(0.02)
        assert app.state.sweep_job.get("status") == "done", app.state.sweep_job
        assert app.state.sweep_job["total"] == 3, "the total grew with the chain"

        # Three points: as written, then *0.9 twice; the extinguished one is kept.
        assert [round(_tau_of(c), 6) for c in solved] == [0.1, 0.09, 0.081]

        store_dir = resolve_store_dir(app.state.preloaded_raw, str(cfg))
        assert store_dir is not None
        identity = scenario_store.config_identity(str(cfg))
        labels = [e["label"] for e in scenario_store.list_entries(store_dir, identity)]
        assert labels == [
            "BASELINE__tau_s=0.1",
            "BASELINE__tau_s=0.09",
            "BASELINE__tau_s=0.081",
        ]
        # The swept value is a plottable attr on every entry (the Sweep results X axis).
        attrs = scenario_store.list_entries(store_dir, identity)
        assert [round(float(a["tau_s"]), 6) for a in attrs] == [0.1, 0.09, 0.081]
    finally:
        client.__exit__(None, None, None)


def test_headless_sweep_runner_executes_a_while_chain_too(tmp_path: Path) -> None:
    """``python -m boulder.sweep_runner`` shares the loop contract with the GUI route.

    The two loops are separate code; both must feed the cursor after every
    step, or the headless runner would silently solve a different chain.
    """
    pytest.importorskip("h5py")
    from unittest.mock import patch

    from boulder import scenario_store, sweep_runner
    from boulder.simulation_worker import SimulationProgress

    cooling = iter([1500.0, 1200.0, 300.0])

    class _CoolingWorker:
        def __init__(self) -> None:
            self.progress = SimulationProgress(is_complete=True)
            self.progress.times = [0.0]
            self.progress.reactors_series = {
                "combustor": {"T": [next(cooling)], "P": [101325.0], "X": {"N2": [1.0]}}
            }

        def start_simulation(self, *a: Any, **kw: Any) -> None:
            pass

        def get_progress(self) -> SimulationProgress:
            return self.progress

    cfg = tmp_path / "chain.yaml"
    cfg.write_text(_CHAIN_YAML, encoding="utf-8")
    with patch(
        "boulder.simulation_worker.SimulationWorker",
        side_effect=lambda: _CoolingWorker(),
    ):
        store_dir = sweep_runner.run(cfg)
    labels = [
        e["label"]
        for e in scenario_store.list_entries(
            store_dir, scenario_store.config_identity(cfg)
        )
    ]
    assert labels == [
        "BASELINE__tau_s=0.1",
        "BASELINE__tau_s=0.09",
        "BASELINE__tau_s=0.081",
    ]
