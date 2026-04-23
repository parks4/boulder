"""Tests for the ``PressureController`` connection type in STONE YAML.

Covers:

- A STONE config with an explicit ``PressureController`` outlet (``K=0``)
  builds, advances, and keeps mass conservation tight at every step
  (``|mdot_in - mdot_out| < 1e-12``).
- The master MFC must exist and be a ``MassFlowController``; missing /
  mistyped masters raise ``ValueError`` with an actionable message.
- ``normalize_config`` reorders connections so a ``PressureController``
  declared *before* its master in the YAML still builds (topological
  sort).
"""

from __future__ import annotations

from typing import Any, Dict, List

import cantera as ct
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config, validate_config


def _pc_two_reactor_config(mdot_in: float = 3.33e-4) -> Dict[str, Any]:
    """Return a minimal STONE config: Reservoir -> Reactor -> Reservoir.

    The first connection is a ``MassFlowController`` with an explicit rate;
    the second is a ``PressureController(pressure_coeff=0)`` that uses the
    first as its ``master`` so ``mdot_out == mdot_in`` at every step.
    """
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            {
                "id": "feed",
                "type": "Reservoir",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "r1",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "outlet",
                "type": "Reservoir",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
        ],
        "connections": [
            {
                "id": "feed_to_r1",
                "type": "MassFlowController",
                "source": "feed",
                "target": "r1",
                "properties": {"mass_flow_rate": mdot_in},
            },
            {
                "id": "r1_to_outlet",
                "type": "PressureController",
                "source": "r1",
                "target": "outlet",
                "properties": {"master": "feed_to_r1", "pressure_coeff": 0.0},
            },
        ],
    }


@pytest.mark.unit
def test_pressure_controller_mass_conservation() -> None:
    """PressureController(K=0) enforces mdot_out = mdot_in at every step.

    Advances the reactor network through several time steps and asserts
    that the absolute difference between the primary MFC's flow and the
    PressureController's flow stays below 1e-12 kg/s - i.e. the
    conservation is enforced *during* transient integration, not only at
    steady state.
    """
    mdot_in = 3.33e-4
    cfg = validate_config(normalize_config(_pc_two_reactor_config(mdot_in)))

    converter = DualCanteraConverter()
    converter.build_network(cfg)

    mfc = converter.connections["feed_to_r1"]
    pc = converter.connections["r1_to_outlet"]
    assert isinstance(mfc, ct.MassFlowController)
    assert isinstance(pc, ct.PressureController)

    net = converter.network
    assert net is not None

    for step_dt in (1e-5, 5e-5, 1e-4, 5e-4):
        net.advance(net.time + step_dt)
        assert abs(mfc.mass_flow_rate - mdot_in) < 1e-12
        assert abs(pc.mass_flow_rate - mdot_in) < 1e-12


def _converter_with_reactors() -> DualCanteraConverter:
    """Return a converter with ``feed``/``r1``/``outlet`` pre-populated.

    Used by the error-path tests below: the staged solver wraps
    ``_build_single_connection`` in a ``try/except-log`` so exceptions
    raised during connection building are swallowed at the orchestration
    level.  To assert the exception *type and message*, we therefore
    exercise :meth:`DualCanteraConverter._build_single_connection`
    directly with the reactors already registered.
    """
    gas = ct.Solution("gri30.yaml")
    gas.TPX = 300.0, 101325.0, "N2:1"
    converter = DualCanteraConverter()
    converter.reactors["feed"] = ct.Reservoir(gas, name="feed")
    r1 = ct.IdealGasReactor(gas, name="r1")
    r1.volume = 1e-5
    converter.reactors["r1"] = r1
    converter.reactors["outlet"] = ct.Reservoir(gas, name="outlet")
    return converter


@pytest.mark.unit
def test_pressure_controller_missing_master_raises() -> None:
    """Missing ``master:`` on a PressureController raises a clear ValueError.

    Asserts the error message tells the user a master is required and
    points the user at the ``master`` field.
    """
    converter = _converter_with_reactors()
    pc_conn = {
        "id": "r1_to_outlet",
        "type": "PressureController",
        "source": "r1",
        "target": "outlet",
        "properties": {"pressure_coeff": 0.0},
    }
    with pytest.raises(ValueError, match="requires a 'master'"):
        converter._build_single_connection(pc_conn)


@pytest.mark.unit
def test_pressure_controller_master_not_found_raises() -> None:
    """Referencing a master id that is not yet built raises ``ValueError``.

    Asserts the error explicitly names the missing master and suggests
    declaring it earlier in ``connections:`` (or via an inlet port).
    """
    converter = _converter_with_reactors()
    pc_conn = {
        "id": "r1_to_outlet",
        "type": "PressureController",
        "source": "r1",
        "target": "outlet",
        "properties": {"master": "no_such_mfc", "pressure_coeff": 0.0},
    }
    with pytest.raises(ValueError, match="master 'no_such_mfc' not found"):
        converter._build_single_connection(pc_conn)


@pytest.mark.unit
def test_pressure_controller_master_wrong_type_raises() -> None:
    """PressureController master that is itself a PressureController is rejected.

    Asserts that referencing a non-MFC as master raises ValueError naming
    the expected type (MassFlowController).
    """
    converter = _converter_with_reactors()
    mfc_conn = {
        "id": "feed_to_r1",
        "type": "MassFlowController",
        "source": "feed",
        "target": "r1",
        "properties": {"mass_flow_rate": 1e-4},
    }
    pc_conn = {
        "id": "r1_to_outlet",
        "type": "PressureController",
        "source": "r1",
        "target": "outlet",
        "properties": {"master": "feed_to_r1", "pressure_coeff": 0.0},
    }
    extra_pc = {
        "id": "extra_pc",
        "type": "PressureController",
        "source": "r1",
        "target": "outlet",
        "properties": {"master": "r1_to_outlet", "pressure_coeff": 0.0},
    }
    converter._build_single_connection(mfc_conn)
    converter._build_single_connection(pc_conn)
    with pytest.raises(ValueError, match="must be a MassFlowController"):
        converter._build_single_connection(extra_pc)


@pytest.mark.unit
def test_pressure_controller_topological_sort() -> None:
    """``normalize_config`` reorders connections so masters precede dependants.

    If the YAML declares the PressureController before its master MFC,
    ``_sort_connections_by_master`` must move it after; otherwise
    Cantera raises at build time.  Asserts the build succeeds and the
    connection list comes back in dependency order.
    """
    cfg = _pc_two_reactor_config()
    cfg["connections"] = [cfg["connections"][1], cfg["connections"][0]]

    normalized = normalize_config(cfg)
    ordered_ids: List[str] = [c["id"] for c in normalized["connections"]]
    assert ordered_ids.index("feed_to_r1") < ordered_ids.index("r1_to_outlet")

    converter = DualCanteraConverter()
    converter.build_network(validate_config(normalized))
    assert isinstance(
        converter.connections["r1_to_outlet"], ct.PressureController
    )
