"""Regression tests: ``ct.Wall(velocity=...)`` round-trips through STONE correctly.

A pure velocity-driven piston (no ``heat_transfer_coeff``/``expansion_rate_coeff``)
must become a real closure-driven wall, not a frozen (typically zero)
``electric_power_kW`` snapshot.

Bug/gap: ``wall.velocity`` always reads back as the evaluated float at the
network's current time (Cantera never returns the underlying Func1/callable),
so a velocity-only wall fell into ``sim_to_internal_config``'s heat-rate
snapshot branch and silently discarded the piston's motion entirely (e.g.
upstream Cantera's ``piston.py``, whose adiabatic free piston is held fixed
until ``t=0.1s`` then moves proportionally to the pressure difference between
its two reactors).
"""

from __future__ import annotations

import ast
import os
import tempfile
import textwrap

import cantera as ct
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.download_script_emitter import CanteraScriptEmitter
from boulder.sim2stone import sim_to_stone_yaml
from boulder.sim2stone_ast import _detect_wall_velocity_closures

_PISTON_SOURCE = """
    import cantera as ct

    gas1 = ct.Solution('h2o2.yaml')
    gas1.TPX = 900.0, ct.one_atm, 'H2:2, O2:1, AR:20'
    gas2 = ct.Solution('gri30.yaml')
    gas2.TPX = 900.0, ct.one_atm, 'CO:2, H2O:0.01, O2:5'

    r1 = ct.IdealGasReactor(gas1)
    r1.volume = 0.5
    r2 = ct.IdealGasReactor(gas2)
    r2.volume = 0.1

    def v(t):
        if t < 0.1:
            return 0.0
        else:
            return (r1.phase.P - r2.phase.P) * 1e-4

    w = ct.Wall(r1, r2, velocity=v)
    sim = ct.ReactorNet([r1, r2])
"""


def _write_and_run(python_content: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(textwrap.dedent(python_content))
        f.flush()
        temp_name = f.name

    try:
        exec_globals: dict = {}
        with open(temp_name, "r") as file:
            exec(file.read(), exec_globals)
        sim = exec_globals["sim"]
        return sim_to_stone_yaml(
            sim,
            default_mechanism="h2o2.yaml",
            source_file=temp_name,
            include_comments=False,
        )
    finally:
        os.unlink(temp_name)


def test_detect_delayed_pressure_proportional_velocity_closure() -> None:
    """AST detection recovers coeff/start_time from piston.py's ``v(t)``."""
    tree = ast.parse(textwrap.dedent(_PISTON_SOURCE))
    closures = _detect_wall_velocity_closures(tree)
    assert len(closures) == 1
    cl = closures[0]
    assert cl.src_reactor_var == "r1"
    assert cl.tgt_reactor_var == "r2"
    assert cl.coeff == pytest.approx(1e-4)
    assert cl.start_time == pytest.approx(0.1)


def test_detect_undelayed_velocity_closure() -> None:
    """A ``def v(t): return coeff*(r1.phase.P - r2.phase.P)`` (no delay) works too."""
    tree = ast.parse(
        textwrap.dedent(
            """
            import cantera as ct
            r1 = ct.IdealGasReactor(gas1)
            r2 = ct.IdealGasReactor(gas2)

            def v(t):
                return 2e-5 * (r1.phase.P - r2.phase.P)

            w = ct.Wall(r1, r2, velocity=v)
            """
        )
    )
    closures = _detect_wall_velocity_closures(tree)
    assert len(closures) == 1
    cl = closures[0]
    assert cl.coeff == pytest.approx(2e-5)
    assert cl.start_time == pytest.approx(0.0)


def test_sim2stone_recovers_velocity_closure_from_source() -> None:
    """A velocity-only Wall emits a pressure_proportional closure, not a torch."""
    yaml_str = _write_and_run(_PISTON_SOURCE)
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    walls = [c for c in normalized["connections"] if c["type"] == "Wall"]
    assert len(walls) == 1
    props = walls[0]["properties"]
    assert "electric_power_kW" not in props
    velocity = props.get("velocity")
    assert isinstance(velocity, dict), f"expected a closure dict, got {velocity!r}"
    assert velocity["closure"] == "pressure_proportional"
    assert velocity["coeff"] == pytest.approx(1e-4)
    assert velocity["start_time"] == pytest.approx(0.1)


def test_cantera_converter_builds_velocity_wall_from_closure_spec() -> None:
    """build_connection constructs a real velocity-driven Wall from the spec."""
    converter = DualCanteraConverter(mechanism="h2o2.yaml")

    nodes = [
        {
            "id": "left",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 900.0,
                "pressure": 2.0 * 101325.0,
                "composition": "H2:2,O2:1,AR:20",
                "volume": 0.5,
            },
        },
        {
            "id": "right",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 900.0,
                "pressure": 101325.0,
                "composition": "H2:1,O2:5",
                "volume": 0.1,
            },
        },
    ]
    conn = {
        "id": "piston",
        "type": "Wall",
        "source": "left",
        "target": "right",
        "properties": {
            "velocity": {
                "closure": "pressure_proportional",
                "coeff": 1e-4,
                "start_time": 0.1,
            },
        },
    }
    for node in nodes:
        converter.build_isolated_reactor(node)
    converter.build_connection(conn)

    wall = converter.walls["piston"]
    net = ct.ReactorNet([converter.reactors["left"], converter.reactors["right"]])
    # Held fixed before start_time...
    net.advance(0.05)
    assert wall.velocity == pytest.approx(0.0)
    # ...then proportional to the (nonzero) pressure difference afterwards.
    net.advance(0.2)
    expected = 1e-4 * (
        converter.reactors["left"].phase.P - converter.reactors["right"].phase.P
    )
    assert wall.velocity == pytest.approx(expected)


def test_cantera_converter_builds_scalar_velocity_wall() -> None:
    """A plain scalar ``velocity:`` builds a constant-velocity Wall."""
    converter = DualCanteraConverter(mechanism="h2o2.yaml")

    nodes = [
        {
            "id": "left",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 900.0,
                "pressure": 101325.0,
                "composition": "H2:1",
                "volume": 0.5,
            },
        },
        {
            "id": "right",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 900.0,
                "pressure": 101325.0,
                "composition": "O2:1",
                "volume": 0.5,
            },
        },
    ]
    conn = {
        "id": "wall_0",
        "type": "Wall",
        "source": "left",
        "target": "right",
        "properties": {"velocity": 0.01},
    }
    for node in nodes:
        converter.build_isolated_reactor(node)
    converter.build_connection(conn)

    wall = converter.walls["wall_0"]
    assert wall.velocity == pytest.approx(0.01)


def test_download_script_emits_velocity_closure_for_pressure_proportional() -> None:
    """The --download script constructs a real def+Func1 for the closure."""
    conn = {
        "id": "piston",
        "type": "Wall",
        "source": "left",
        "target": "right",
        "properties": {
            "velocity": {
                "closure": "pressure_proportional",
                "coeff": 1e-4,
                "start_time": 0.1,
            },
        },
    }
    emitter = CanteraScriptEmitter()
    lines = emitter._emit_connection(conn, "_conn_piston", "_conn_piston_spec")
    joined = "\n".join(lines)
    assert "def _velocity__conn_piston(" in joined
    assert "velocity=ct.Func1(_velocity__conn_piston)" in joined
    assert "raise ValueError" not in joined


def test_download_script_emits_scalar_velocity_kwarg() -> None:
    """The --download script passes a plain float velocity through directly."""
    conn = {
        "id": "wall_0",
        "type": "Wall",
        "source": "left",
        "target": "right",
        "properties": {"velocity": 0.01},
    }
    emitter = CanteraScriptEmitter()
    lines = emitter._emit_connection(conn, "_conn_wall_0", "_conn_wall_0_spec")
    joined = "\n".join(lines)
    assert "velocity=0.01" in joined
