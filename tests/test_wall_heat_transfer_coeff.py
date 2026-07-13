"""Regression tests: ct.Wall(A=, U=) round-trips through STONE correctly.

It must become a real dynamic heat-conduction wall, not a frozen
electric_power_kW snapshot.

Bug: sim2stone converted every ct.Wall by reading its *instantaneous*
``heat_rate`` at conversion time and baking it into a constant
``electric_power_kW``. For a passive U/A wall (e.g. upstream's
``ct.Wall(cstr, env, A=1.0, U=0.02)`` in periodic_cstr.py), both sides
typically start at the same temperature, so heat_rate is ~0 at that instant —
the emitted wall silently became a permanent no-op, discarding the U/A
coupling the whole example's oscillatory behaviour depends on
("We need to have heat loss to see the oscillations" — periodic_cstr.py).
"""

from __future__ import annotations

import cantera as ct
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.download_script_emitter import CanteraScriptEmitter
from boulder.sim2stone import sim_to_stone_yaml


def _build_two_reactor_wall_network(U: float = 0.02):
    gas = ct.Solution("h2o2.yaml")
    gas.TPX = 770.0, 60.0 * 133.3, "H2:2, O2:1"
    r1 = ct.IdealGasReactor(gas, name="cstr")
    env = ct.Reservoir(gas, name="env")
    ct.Wall(r1, env, A=1.0, U=U, name="wall_0")
    sim = ct.ReactorNet([r1])
    return sim


def test_sim2stone_preserves_heat_transfer_coeff() -> None:
    """A U/A wall emits heat_transfer_coeff, not a frozen electric_power_kW."""
    sim = _build_two_reactor_wall_network(U=0.02)
    yaml_str = sim_to_stone_yaml(sim, default_mechanism="h2o2.yaml")
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    (wall,) = [c for c in normalized["connections"] if c["id"] == "wall_0"]
    assert wall["properties"].get("heat_transfer_coeff") == pytest.approx(0.02)
    assert "electric_power_kW" not in wall["properties"]


def test_sim2stone_zero_u_falls_back_to_electric_power() -> None:
    """Torch-style wall (no U) must still use the electric_power_kW path.

    This fix must not regress that case.
    """
    gas = ct.Solution("gri30.yaml")
    gas.TPX = 1500.0, ct.one_atm, "CH4:1"
    r1 = ct.IdealGasReactor(gas, name="combustor")
    env = ct.Reservoir(gas, name="env")
    ct.Wall(r1, env, A=1.0, Q=lambda t: 500.0, name="torch")
    sim = ct.ReactorNet([r1])

    yaml_str = sim_to_stone_yaml(sim, default_mechanism="gri30.yaml")
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    (wall,) = [c for c in normalized["connections"] if c["id"] == "torch"]
    assert "heat_transfer_coeff" not in wall["properties"]
    assert wall["properties"].get("electric_power_kW") == pytest.approx(0.5)


def test_cantera_converter_builds_dynamic_wall_from_heat_transfer_coeff() -> None:
    """build_connection constructs a real U/A wall, not a fixed-Q one.

    build_isolated_reactor is the documented single source of truth for
    reactor construction outside a full staged-solver build — it registers
    into converter.reactors[rid], which build_connection then requires.
    """
    converter = DualCanteraConverter(mechanism="h2o2.yaml")

    nodes = [
        {
            "id": "cstr",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 770.0,
                "pressure": 60.0 * 133.3,
                "composition": "H2:0.6667,O2:0.3333",
                "volume": 1e-5,
            },
        },
        {
            "id": "env",
            "type": "Reservoir",
            "properties": {
                "temperature": 770.0,
                "pressure": 60.0 * 133.3,
                "composition": "H2:0.6667,O2:0.3333",
            },
        },
    ]
    conn = {
        "id": "wall_0",
        "type": "Wall",
        "source": "cstr",
        "target": "env",
        "properties": {"heat_transfer_coeff": 0.02, "area": 1.0},
    }
    for node in nodes:
        converter.build_isolated_reactor(node)
    converter.build_connection(conn)

    wall = converter.walls["wall_0"]
    assert wall.heat_transfer_coeff == pytest.approx(0.02)
    assert wall.area == pytest.approx(1.0)


def test_download_script_emits_u_kwarg_for_heat_transfer_coeff() -> None:
    """The --download script constructs ct.Wall(..., U=...), not Q=lambda."""
    conn = {
        "id": "wall_0",
        "type": "Wall",
        "source": "cstr",
        "target": "env",
        "properties": {"heat_transfer_coeff": 0.02, "area": 1.0},
    }
    emitter = CanteraScriptEmitter()
    lines = emitter._emit_connection(conn, "_conn_wall_0", "_conn_wall_0_spec")
    joined = "\n".join(lines)
    assert "U=0.02" in joined
    assert "Q=lambda" not in joined


def test_sim2stone_preserves_expansion_rate_coeff() -> None:
    """A moving piston wall (K=) emits expansion_rate_coeff alongside U/area.

    Without K, Cantera's Wall/Reactor ODE system never moves the piston, so a
    two-reactor network driven mainly by piston-compression (e.g. upstream's
    reactor2.py) loses that dynamic almost entirely -- the reactors only
    exchange heat, not volume.
    """
    gas = ct.Solution("h2o2.yaml")
    gas.TPX = 1000.0, 20.0 * ct.one_atm, "H2:1"
    r1 = ct.IdealGasReactor(gas, name="left")
    gas.TPX = 500.0, 0.2 * ct.one_atm, "O2:1"
    r2 = ct.IdealGasReactor(gas, name="right")
    ct.Wall(r2, r1, A=1.0, K=0.5e-4, U=100.0, name="piston")
    sim = ct.ReactorNet([r1, r2])

    yaml_str = sim_to_stone_yaml(sim, default_mechanism="h2o2.yaml")
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    (wall,) = [c for c in normalized["connections"] if c["id"] == "piston"]
    assert wall["properties"].get("expansion_rate_coeff") == pytest.approx(0.5e-4)
    assert wall["properties"].get("heat_transfer_coeff") == pytest.approx(100.0)


def test_cantera_converter_builds_moving_wall_from_expansion_rate_coeff() -> None:
    """build_connection passes K through so Cantera moves the piston itself."""
    converter = DualCanteraConverter(mechanism="h2o2.yaml")

    nodes = [
        {
            "id": "left",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 1000.0,
                "pressure": 20.0 * 101325.0,
                "composition": "H2:1",
                "volume": 1.0,
            },
        },
        {
            "id": "right",
            "type": "IdealGasReactor",
            "properties": {
                "temperature": 500.0,
                "pressure": 0.2 * 101325.0,
                "composition": "O2:1",
                "volume": 1.0,
            },
        },
    ]
    conn = {
        "id": "piston",
        "type": "Wall",
        "source": "right",
        "target": "left",
        "properties": {
            "heat_transfer_coeff": 100.0,
            "expansion_rate_coeff": 0.5e-4,
            "area": 1.0,
        },
    }
    for node in nodes:
        converter.build_isolated_reactor(node)
    converter.build_connection(conn)

    wall = converter.walls["piston"]
    assert wall.expansion_rate_coeff == pytest.approx(0.5e-4)
    assert wall.heat_transfer_coeff == pytest.approx(100.0)


def test_download_script_emits_k_kwarg_for_expansion_rate_coeff() -> None:
    """The --download script constructs ct.Wall(..., K=...) for a piston."""
    conn = {
        "id": "piston",
        "type": "Wall",
        "source": "right",
        "target": "left",
        "properties": {
            "heat_transfer_coeff": 100.0,
            "expansion_rate_coeff": 0.5e-4,
            "area": 1.0,
        },
    }
    emitter = CanteraScriptEmitter()
    lines = emitter._emit_connection(conn, "_conn_piston", "_conn_piston_spec")
    joined = "\n".join(lines)
    assert "K=5e-05" in joined
    assert "U=100.0" in joined
