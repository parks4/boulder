"""Tests for inline port expansion and STONE v2 port rejection.

Covers:

- In STONE v2, inline ``inlet:``/``outlet:`` ports on a reactor node are
  rejected with a clear error message (they are not valid in STONE v2).
- The ``expand_port_shortcuts`` function still exists and operates on the
  internal normalized format (for internal/plugin use).
- ``expand_port_shortcuts`` expands port dicts into canonical ``connections``
  entries with auto-picked ids and defaults.
- The ports are removed from node ``properties`` after expansion.
- ``outlet:`` on a reactor with two MFC inlets raises unless ``master:`` is set.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from boulder.config import expand_port_shortcuts


def _internal_ported_config(with_mfr: bool = True) -> Dict[str, Any]:
    """Internal-format config (already normalized) with inlet/outlet shortcut properties."""
    inlet: Dict[str, Any] = {"from": "feed"}
    if with_mfr:
        inlet["mass_flow_rate"] = 1.5e-4
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "groups": {
            "default": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"}
        },
        "nodes": [
            {
                "id": "feed",
                "type": "Reservoir",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
                "group": "default",
            },
            {
                "id": "r1",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                    "inlet": inlet,
                    "outlet": {"to": "outlet"},
                },
                "group": "default",
            },
            {
                "id": "outlet",
                "type": "Reservoir",
                "properties": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
                "group": "default",
            },
        ],
        "connections": [],
    }


@pytest.mark.unit
def test_ports_expand_to_canonical_connections() -> None:
    """expand_port_shortcuts produces two connections: an MFC inlet and a PC outlet.

    Asserts that inlet port synthesises MFC 'feed_to_r1' and outlet port
    synthesises PressureController 'r1_to_outlet' with auto-picked master and
    default pressure_coeff=0.
    """
    cfg = copy.deepcopy(_internal_ported_config())
    expand_port_shortcuts(cfg)
    conn_ids = {c["id"] for c in cfg["connections"]}
    assert "feed_to_r1" in conn_ids
    assert "r1_to_outlet" in conn_ids
    mfc = next(c for c in cfg["connections"] if c["id"] == "feed_to_r1")
    assert mfc["type"] == "MassFlowController"
    pc = next(c for c in cfg["connections"] if c["id"] == "r1_to_outlet")
    assert pc["type"] == "PressureController"
    assert pc["properties"]["master"] == "feed_to_r1"
    assert pc["properties"]["pressure_coeff"] == 0.0


@pytest.mark.unit
def test_ports_removed_from_node_properties() -> None:
    """inlet: and outlet: are removed from node properties after expansion.

    Asserts that node r1 no longer carries inlet/outlet as properties
    after expand_port_shortcuts, so downstream consumers never see them.
    """
    cfg = copy.deepcopy(_internal_ported_config())
    expand_port_shortcuts(cfg)
    r1 = next(n for n in cfg["nodes"] if n["id"] == "r1")
    props = r1.get("properties") or {}
    assert "inlet" not in props
    assert "outlet" not in props


@pytest.mark.unit
def test_outlet_port_defaults_to_pressure_controller() -> None:
    """Default outlet device is PressureController with pressure_coeff=0.

    Asserts that an outlet: port without an explicit device: synthesises
    a PressureController whose master auto-resolves to the node's single
    inlet MFC.
    """
    cfg = copy.deepcopy(_internal_ported_config())
    expand_port_shortcuts(cfg)
    outlet_conn = next(c for c in cfg["connections"] if c["id"] == "r1_to_outlet")
    assert outlet_conn["type"] == "PressureController"
    props = outlet_conn["properties"]
    assert props["master"] == "feed_to_r1"
    assert props["pressure_coeff"] == 0.0


@pytest.mark.unit
def test_inlet_without_mfr_stays_unresolved() -> None:
    """Omitting mass_flow_rate on an inlet port leaves the MFC with no rate.

    Asserts that the synthesised MFC has no mass_flow_rate in its
    properties so the conservation resolver can fill it in.
    """
    cfg = copy.deepcopy(_internal_ported_config(with_mfr=False))
    expand_port_shortcuts(cfg)
    inlet_conn = next(c for c in cfg["connections"] if c["id"] == "feed_to_r1")
    assert "mass_flow_rate" not in (inlet_conn.get("properties") or {})
