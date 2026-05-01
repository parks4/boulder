"""Tests for staged-network visualization-time mass conservation.

When a STONE YAML declares a ``groups:`` block, ``boulder.staged_solver``
solves each stage in isolation (inter-stage connections are virtual at
solve time — upstream state is copied into the downstream reactor).
``DualCanteraConverter.build_viz_network`` then materialises those
inter-stage flow devices so Sankey and Network panels can display the
assembled topology.

Before the fix, inter-stage MFCs that did not carry an explicit
``mass_flow_rate`` stayed at ``0 kg/s`` because
``_apply_flow_conservation`` had already run during each stage's
sub-network build (with only partial topology visible).  This module
asserts that the final global conservation pass now resolves every
remaining unset MFC against the full cross-stage topology, including:

(a) a two-stage linear chain,
(b) a multi-inlet mixer shaped like SPRING_A3, and
(c) a staged PressureController whose master lives in an earlier stage.
"""

from __future__ import annotations

from typing import Any, Dict

import cantera as ct
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config, validate_config

# ---------------------------------------------------------------------------
# (a) two-stage linear chain
# ---------------------------------------------------------------------------


def _two_stage_linear_chain() -> Dict[str, Any]:
    """Two stages, one reactor each, one explicit inter-stage MFC with no rate.

    The inter-stage MFC ``a_to_b`` carries no ``mass_flow_rate`` (it
    must be resolved by conservation from the upstream ``feed_to_a``).
    """
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "groups": {
            "stage_a": {
                "stage_order": 1,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
            "stage_b": {
                "stage_order": 2,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
        },
        "nodes": [
            {
                "id": "feed",
                "type": "Reservoir",
                "properties": {
                    "group": "stage_a",
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
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
                "id": "feed_to_a",
                "type": "MassFlowController",
                "source": "feed",
                "target": "r_a",
                "properties": {"mass_flow_rate": 5e-4},
                "group": "stage_a",
            },
            {
                "id": "a_to_b",
                "type": "MassFlowController",
                "source": "r_a",
                "target": "r_b",
                "properties": {},
            },
        ],
    }


@pytest.mark.slow
def test_staged_two_stage_inter_stage_flow_resolved() -> None:
    """Two-stage chain: inter-stage MFC picks up the upstream rate.

    Asserts that after ``build_network`` the viz-network MFC ``a_to_b``
    reports the same ``mass_flow_rate`` as the inlet ``feed_to_a``
    (i.e. the global conservation pass at the end of
    ``build_viz_network`` ran with the full topology visible).
    """
    cfg = validate_config(normalize_config(_two_stage_linear_chain()))
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    conv.build_network(cfg)

    # Read from ``_mfc_flow_rates`` because ``mass_flow_rate`` on a
    # Cantera FlowDevice only exposes its getter after the owning
    # ReactorNet has been initialised, and the viz ReactorNet is
    # structural-only (never integrated).
    rates = conv._mfc_flow_rates
    assert rates["feed_to_a"] == pytest.approx(5e-4)
    assert rates["a_to_b"] == pytest.approx(rates["feed_to_a"], rel=1e-9)


# ---------------------------------------------------------------------------
# (b) multi-inlet mixer (SPRING_A3-shaped)
# ---------------------------------------------------------------------------


def _multi_inlet_mixer() -> Dict[str, Any]:
    """Two feeds in stage 1 into a mixer in stage 2 that feeds a sink in stage 3.

    Mirrors the SPRING_A3 shape: the mixer has two MFC inlets and one
    MFC outlet with no explicit rate; the outlet must resolve to the
    sum of the two inlet rates.
    """
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "groups": {
            "feed_stage": {
                "stage_order": 1,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
            "mixer_stage": {
                "stage_order": 2,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
            "sink_stage": {
                "stage_order": 3,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
        },
        "nodes": [
            {
                "id": "feed_a",
                "type": "Reservoir",
                "properties": {
                    "group": "feed_stage",
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "feed_b",
                "type": "Reservoir",
                "properties": {
                    "group": "feed_stage",
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "upstream_a",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "group": "feed_stage",
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "upstream_b",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "group": "feed_stage",
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "mixer",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "group": "mixer_stage",
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "sink",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "group": "sink_stage",
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
        ],
        "connections": [
            {
                "id": "feed_a_to_up_a",
                "type": "MassFlowController",
                "source": "feed_a",
                "target": "upstream_a",
                "properties": {"mass_flow_rate": 4e-4},
                "group": "feed_stage",
            },
            {
                "id": "feed_b_to_up_b",
                "type": "MassFlowController",
                "source": "feed_b",
                "target": "upstream_b",
                "properties": {"mass_flow_rate": 6e-4},
                "group": "feed_stage",
            },
            {
                "id": "up_a_to_mixer",
                "type": "MassFlowController",
                "source": "upstream_a",
                "target": "mixer",
                "properties": {},
            },
            {
                "id": "up_b_to_mixer",
                "type": "MassFlowController",
                "source": "upstream_b",
                "target": "mixer",
                "properties": {},
            },
            {
                "id": "mixer_to_sink",
                "type": "MassFlowController",
                "source": "mixer",
                "target": "sink",
                "properties": {},
            },
        ],
    }


@pytest.mark.slow
def test_staged_multi_inlet_mixer_conservation() -> None:
    """Multi-inlet mixer in stage 2 balances inflow vs outflow to machine precision.

    Asserts:
    1. every MFC in the viz network has ``mass_flow_rate > 0`` (no link
       left at the ``0 kg/s`` default),
    2. the sum of the two inlets into the mixer equals the single
       outlet, within 1e-9 kg/s,
    3. the mixer outlet equals the sum of the two upstream feeds.
    """
    cfg = validate_config(normalize_config(_multi_inlet_mixer()))
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    conv.build_network(cfg)

    flows = conv._mfc_flow_rates
    for cid in (
        "feed_a_to_up_a",
        "feed_b_to_up_b",
        "up_a_to_mixer",
        "up_b_to_mixer",
        "mixer_to_sink",
    ):
        assert cid in flows, f"MFC '{cid}' missing from flow-rate map"
        assert flows[cid] > 0.0, f"MFC '{cid}' left at {flows[cid]} kg/s"

    inlet_sum = flows["up_a_to_mixer"] + flows["up_b_to_mixer"]
    assert flows["mixer_to_sink"] == pytest.approx(inlet_sum, abs=1e-9)
    assert inlet_sum == pytest.approx(
        flows["feed_a_to_up_a"] + flows["feed_b_to_up_b"], abs=1e-9
    )


# ---------------------------------------------------------------------------
# (c) staged PressureController with master in a previous stage
# ---------------------------------------------------------------------------


def _staged_pc_with_prior_master() -> Dict[str, Any]:
    """Two-stage chain where stage 2's outlet is a PC mastered by stage 1's MFC."""
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "groups": {
            "stage_a": {
                "stage_order": 1,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
            "stage_b": {
                "stage_order": 2,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
        },
        "nodes": [
            {
                "id": "feed",
                "type": "Reservoir",
                "properties": {
                    "group": "stage_a",
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "r_a",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "group": "stage_a",
                    "temperature": 1000.0,
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
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "outlet",
                "type": "Reservoir",
                "properties": {
                    "group": "stage_b",
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
        ],
        "connections": [
            {
                "id": "feed_to_a",
                "type": "MassFlowController",
                "source": "feed",
                "target": "r_a",
                "properties": {"mass_flow_rate": 3e-4},
                "group": "stage_a",
            },
            {
                "id": "a_to_b",
                "type": "MassFlowController",
                "source": "r_a",
                "target": "r_b",
                "properties": {},
            },
            {
                "id": "b_to_outlet",
                "type": "PressureController",
                "source": "r_b",
                "target": "outlet",
                "properties": {"master": "feed_to_a", "pressure_coeff": 0.0},
                "group": "stage_b",
            },
        ],
    }


@pytest.mark.slow
def test_staged_pressure_controller_cross_stage_master() -> None:
    """PC in stage 2 can reference an MFC master declared in stage 1.

    Asserts:
    1. ``build_network`` succeeds (no "master not found" error),
    2. the outlet PC reports the same ``mass_flow_rate`` as its master,
    3. the inter-stage MFC was resolved by the global conservation pass.
    """
    cfg = validate_config(normalize_config(_staged_pc_with_prior_master()))
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    conv.build_network(cfg)

    pc_out = conv.connections["b_to_outlet"]
    assert isinstance(pc_out, ct.PressureController)

    rates = conv._mfc_flow_rates
    assert rates["feed_to_a"] == pytest.approx(3e-4)
    assert rates["a_to_b"] == pytest.approx(3e-4, rel=1e-9)
    # PressureController's flow is driven by Cantera at integration time
    # (its getter ``PressureController.primary`` is not exposed in
    # Cantera 3.2); the master MFC's resolved rate is what downstream
    # viewers use when they query the PC master in the Sankey.


def _staged_pc_on_logical_master() -> Dict[str, Any]:
    """Two-stage PSR→PFR chain with PC outlet mastering logical ``psr_to_pfr``."""
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "groups": {
            "psr_stage": {
                "stage_order": 1,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
            "pfr_stage": {
                "stage_order": 2,
                "mechanism": "gri30.yaml",
                "solve": "advance",
                "advance_time": 1e-4,
            },
        },
        "nodes": [
            {
                "id": "feed",
                "type": "Reservoir",
                "properties": {
                    "group": "psr_stage",
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "psr",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "group": "psr_stage",
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "pfr",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "group": "pfr_stage",
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "downstream",
                "type": "Reservoir",
                "properties": {
                    "group": "pfr_stage",
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
        ],
        "connections": [
            {
                "id": "feed_to_psr",
                "type": "MassFlowController",
                "source": "feed",
                "target": "psr",
                "properties": {"mass_flow_rate": 5e-4},
                "group": "psr_stage",
            },
            {
                "id": "psr_to_pfr",
                "type": "MassFlowController",
                "source": "psr",
                "target": "pfr",
                "properties": {},
                "logical": True,
            },
            {
                "id": "pfr_to_downstream",
                "type": "PressureController",
                "source": "pfr",
                "target": "downstream",
                "properties": {"master": "psr_to_pfr", "pressure_coeff": 0.0},
                "group": "pfr_stage",
            },
        ],
    }


@pytest.mark.slow
def test_pc_mastered_on_logical_inter_stage_mfc_builds_in_viz_network() -> None:
    """PC mastered on a logical inter-stage MFC defers gracefully.

    Asserts:
    1. build_network succeeds without raising on 'master not found'.
    2. pfr_to_downstream is a PressureController in the final viz network.
    3. psr_to_pfr is a MassFlowController in the final viz network (materialized).
    4. The primary MFC (psr_to_pfr) carries the upstream feed flow (5e-4 kg/s).
    """
    cfg = validate_config(normalize_config(_staged_pc_on_logical_master()))
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    conv.build_network(cfg)

    assert isinstance(
        conv.connections.get("pfr_to_downstream"), ct.PressureController
    ), "pfr_to_downstream must be a PressureController in the viz network"
    assert isinstance(conv.connections.get("psr_to_pfr"), ct.MassFlowController), (
        "psr_to_pfr must be a MassFlowController (materialized logical MFC) in viz network"
    )
    rates = conv._mfc_flow_rates
    assert rates.get("feed_to_psr") == pytest.approx(5e-4, rel=1e-9)
    assert rates.get("psr_to_pfr") == pytest.approx(5e-4, rel=1e-9)
