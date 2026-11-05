"""Review-round fixes of the one-run pipeline (neutral configs only).

Each test states the behaviour it pins: a GUI time override reaching an
``advance`` solve, the startup lookup hashing like check-cache, ``prepare_scenario``
validating by default, the fingerprint ignoring GUI branding, the stream-point
display after a mechanism switch, the one time-grid rule, and
``BoulderRunner.build()`` applying bindings.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import cantera as ct
import pytest

from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter
from boulder.runner import BoulderRunner
from boulder.sweep_runner import (
    converter_mechanism_resolver,
    prepare_entry,
    prepare_scenario,
    solver_window,
    with_time_overrides,
)

_ADVANCE: Dict[str, Any] = {
    "metadata": {},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "settings": {"solver": {"kind": "advance", "advance_time": 1.0e-3}},
    "network": [
        {
            "id": "r",
            "IdealGasReactor": {
                "volume": 1.0,
                "initial": {
                    "temperature": 500,
                    "pressure": 101325,
                    "composition": "N2:1",
                },
            },
        }
    ],
}


def test_time_override_reaches_an_advance_solve() -> None:
    """A GUI run-time override on ``kind: advance`` moves the solve's end time.

    The ``advance`` dispatch reads only ``advance_time``: the override must land
    there (and change the fingerprint), not only in ``solver.grid``.
    """
    resolve = converter_mechanism_resolver(DualCanteraConverter)
    base = prepare_scenario(copy.deepcopy(_ADVANCE), resolve)
    raw = with_time_overrides(copy.deepcopy(_ADVANCE), 2.0e-3, None)
    config, _, fingerprint = prepare_scenario(raw, resolve)

    conv = DualCanteraConverter()
    conv.build_network(config)

    assert conv._staged_trajectory.networks["default"].time == pytest.approx(2.0e-3)
    assert fingerprint != base[2]


def _startup_app(cfg_path: Path):
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from boulder.api.main import create_app  # noqa: PLC0415

    os.environ["BOULDER_CONFIG_PATH"] = str(cfg_path)
    try:
        app = create_app()
        client = TestClient(app)
        client.__enter__()
    finally:
        del os.environ["BOULDER_CONFIG_PATH"]
    return client, app


def test_startup_cached_badge_uses_the_check_cache_fingerprint(
    tmp_path: Path,
) -> None:
    """An entry stored under the base entry's fingerprint is found at startup.

    With a ``scenarios:`` section the base entry is ``BASELINE``; the startup
    lookup must hash it through ``prepare_entry`` like check-cache and the run.
    """
    pytest.importorskip("fastapi")
    import yaml  # noqa: PLC0415

    from boulder import scenario_store  # noqa: PLC0415
    from boulder.runset import base_entry_id, resolve_store_dir  # noqa: PLC0415

    raw = {**copy.deepcopy(_ADVANCE), "scenarios": {"hot": {}}}
    cfg = tmp_path / "model.yaml"
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")
    loaded = BoulderRunner.load(str(cfg))
    fingerprint = prepare_entry(loaded, base_entry_id(loaded))[2]
    store_dir = resolve_store_dir(loaded, str(cfg))
    assert store_dir is not None
    scenario_store.write_entry(
        store_dir,
        base_entry_id(loaded),
        gui_payload={
            "status": "complete",
            "times": [0.0],
            "reactors_series": {},
            "reactor_reports": {},
            "connection_reports": {},
            "code_str": "",
        },
        mechanism="gri30.yaml",
        fingerprint=fingerprint,
        identity=scenario_store.config_identity(str(cfg)),
    )

    with patch("boulder.sweep_runner.prepare_entry", wraps=prepare_entry) as spy:
        client, app = _startup_app(cfg)
    try:
        spy.assert_called_once()
        assert app.state.preloaded_fingerprint == fingerprint
    finally:
        client.__exit__(None, None, None)


def test_prepare_scenario_validates_by_default() -> None:
    """Without a ``runner_cls`` the config still goes through the runner's validate."""
    with patch.object(
        BoulderRunner, "validate", wraps=BoulderRunner.validate
    ) as validate:
        prepare_scenario(copy.deepcopy(_ADVANCE), None)
    validate.assert_called_once()


@pytest.mark.parametrize("key", ["gui_app_title", "gui_app_version"])
def test_fingerprint_ignores_gui_branding(key: str) -> None:
    """``metadata.gui_app_title`` / ``gui_app_version`` are display-only."""
    plain = copy.deepcopy(_ADVANCE)
    a = prepare_scenario(copy.deepcopy(plain), None)[2]
    branded = copy.deepcopy(plain)
    branded["metadata"][key] = "1.2.3"
    b = prepare_scenario(branded, None)[2]
    branded["metadata"][key] = "9.9.9"
    c = prepare_scenario(branded, None)[2]
    assert a == b == c


_SWITCH: Dict[str, Any] = {
    "groups": {
        "stage_a": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"},
        "stage_b": {"mechanism": "h2o2.yaml", "solve": "advance_to_steady_state"},
    },
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "nodes": [
        {
            "id": "r_a",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_a",
                "temperature": 500.0,
                "pressure": 101325.0,
                "composition": "N2:1, CO2:1",
                "volume": 1e-5,
            },
        },
        {
            "id": "r_b",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_b",
                "temperature": 500.0,
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
            "mechanism_switch": {"htol": 1e-2, "Xtol": 1e-2},
        },
    ],
}


def _by_name_switch(gas: Any, target: str, htol: float, Xtol: float) -> Any:
    """Neutral ``mechanism_switch_fn``: keep the species the target knows."""
    out = ct.Solution(target)
    known = {s: x for s, x in zip(gas.species_names, gas.X) if s in out.species_names}
    out.TPX = gas.T, gas.P, known
    return out


def test_stream_point_display_uses_the_pre_switch_gas() -> None:
    """After a mechanism switch the stream point shows the source-mechanism gas.

    Same convention as ``BoulderRunner.solve_stage``: CO2 is dropped by the
    switch, but the display (``top_Y``) still reports it.
    """
    plugins = BoulderPlugins()
    plugins.mechanism_switch_fn = _by_name_switch
    conv = DualCanteraConverter(mechanism="gri30.yaml", plugins=plugins)
    conv.build_network(copy.deepcopy(_SWITCH))

    top_y = conv.reactor_meta["r_a_outlet"]["top_Y"]
    assert "CO2" in top_y


_BOUND = """
metadata:
  title: bindings through build
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_grid
    grid: {start: 0.0, stop: 0.01, dt: 0.001}
signals:
  - id: mdot_const
    Constant:
      value: 0.002
network:
- id: upstream
  Reservoir: {temperature: 600.0, pressure: 101325.0, composition: "CH4:1, N2:3.76"}
- id: reactor
  IdealGasReactor:
    volume: 0.001
    initial: {temperature: 300.0, pressure: 101325.0, composition: "CH4:1, N2:3.76"}
- id: downstream
  Reservoir: {temperature: 300.0, pressure: 101325.0, composition: "CH4:1, N2:3.76"}
- id: inlet_mfc
  source: upstream
  target: reactor
  MassFlowController: {mass_flow_rate: 0.001}
- id: outlet_valve
  source: reactor
  target: downstream
  PressureController: {master: inlet_mfc, pressure_coeff: 0.0}
"""


def test_runner_build_applies_bindings() -> None:
    """``BoulderRunner.build()`` drives the MFC from its binding, not the static value."""
    import yaml  # noqa: PLC0415

    static = yaml.safe_load(_BOUND)
    bound = copy.deepcopy(static)
    bound["bindings"] = [
        {"source": "mdot_const", "target": "connections.inlet_mfc.mass_flow_rate"}
    ]

    def end_temperature(cfg: Dict[str, Any]) -> float:
        prepared = BoulderRunner.validate(BoulderRunner.normalize(cfg))
        runner = BoulderRunner(config=prepared)
        runner.build()
        assert runner.converter is not None
        return float(runner.converter.reactors["reactor"].phase.T)

    assert end_temperature(bound) != pytest.approx(end_temperature(static), abs=1e-3)


def test_solver_window_list_grid_returns_its_real_end() -> None:
    """An explicit list of save times gives its last time, not ``(0, 0)``."""
    cfg = {"settings": {"solver": {"kind": "advance_grid", "grid": [0.1, 0.2, 0.5]}}}
    assert solver_window(cfg)[0] == pytest.approx(0.5)


def test_solver_window_follows_what_the_solve_uses() -> None:
    """``grid.stop`` wins over ``settings.end_time``: the grid is what is integrated."""
    cfg = {
        "settings": {
            "end_time": 0.05,
            "solver": {"kind": "advance_grid", "grid": {"stop": 0.02, "dt": 0.001}},
        }
    }
    assert solver_window(cfg) == pytest.approx((0.02, 0.001))


_STAGED_ADVANCE: Dict[str, Any] = {
    "metadata": {},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "settings": {"solver": {"kind": "advance", "advance_time": 2.0e-2}},
    "stages": {
        "s1": {
            "mechanism": "gri30.yaml",
            "solver": {"kind": "advance", "advance_time": 2.0e-2},
        }
    },
    "s1": [
        {
            "id": "r",
            "IdealGasReactor": {
                "volume": 1.0,
                "initial": {
                    "temperature": 500,
                    "pressure": 101325,
                    "composition": "N2:1",
                },
            },
        }
    ],
}


@pytest.mark.parametrize("override", [(5.0e-3, None), (None, 1.0e-3)])
def test_time_override_is_rejected_for_a_staged_config(override: Any) -> None:
    """A run-time/step override on a config with ``stages:`` raises ``ValueError``.

    Each stage declares its own ``advance_time``, which wins over the global
    one: accepting the override would store a definition that claims a time
    that was never solved.
    """
    with pytest.raises(ValueError, match="advance_time per stage"):
        with_time_overrides(copy.deepcopy(_STAGED_ADVANCE), *override)


def test_server_rejects_a_time_override_for_a_staged_config(tmp_path: Path) -> None:
    """``POST /api/simulations`` answers 422 for a time override on a staged config."""
    pytest.importorskip("fastapi")
    import yaml  # noqa: PLC0415

    cfg = tmp_path / "staged.yaml"
    cfg.write_text(yaml.safe_dump(_STAGED_ADVANCE), encoding="utf-8")
    client, _ = _startup_app(cfg)
    try:
        resp = client.post("/api/simulations", json={"simulation_time": 5.0e-3})
        assert resp.status_code == 422, resp.text
        assert "advance_time per stage" in resp.text
        resp = client.post(
            "/api/simulations/check-cache", json={"simulation_time": 5.0e-3}
        )
        assert resp.status_code == 422, resp.text
    finally:
        client.__exit__(None, None, None)


def _shift_switch(gas: Any, target: str, htol: float, Xtol: float) -> Any:
    """Switch that moves T by +50 K: the post-switch gas differs from the pre-switch gas."""
    out = _by_name_switch(gas, target, htol, Xtol)
    out.TP = gas.T + 50.0, gas.P
    return out


def test_stream_point_node_shows_the_pre_switch_temperature() -> None:
    """After a switch the stream node's T and P are the pre-switch gas's.

    Same gas as its density, enthalpy and ``top_Y``: with a switch that shifts T
    by 50 K, the node's ``temperature`` is the source reactor's, not the shifted one.
    """
    plugins = BoulderPlugins()
    plugins.mechanism_switch_fn = _shift_switch
    conv = DualCanteraConverter(mechanism="gri30.yaml", plugins=plugins)
    conv.build_network(copy.deepcopy(_SWITCH))

    assert conv._last_config is not None
    node = next(n for n in conv._last_config["nodes"] if n["id"] == "r_a_outlet")
    source_t = float(conv.reactors["r_a"].phase.T)
    assert node["properties"]["temperature"] == pytest.approx(source_t)
    assert node["properties"]["pressure"] == pytest.approx(
        float(conv.reactors["r_a"].phase.P)
    )
