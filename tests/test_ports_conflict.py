"""Tests for port/connection conflict detection in expand_port_shortcuts.

When an internal-format config declares both a node-level inlet:/outlet:
property and an explicit connection that would produce the same id (or
same source/target edge), expand_port_shortcuts must raise rather than
silently override. Also covers multi-inlet ambiguity for PC outlets.

Note: In STONE v2, inline inlet:/outlet: port syntax is rejected at parse
time. These tests exercise the internal expand_port_shortcuts function
which operates on the internal normalized format and is used by plugins.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from boulder.config import expand_port_shortcuts


def _internal_node(nid: str, kind: str, **props: Any) -> Dict[str, Any]:
    """Create an internal-format node dict."""
    return {"id": nid, "type": kind, "properties": props, "group": "default"}


def _internal_conn(
    cid: str, kind: str, source: str, target: str, **props: Any
) -> Dict[str, Any]:
    return {
        "id": cid,
        "type": kind,
        "source": source,
        "target": target,
        "properties": props,
    }


@pytest.mark.unit
def test_inlet_port_conflicts_with_explicit_connection() -> None:
    """Inlet port + explicit MFC on the same edge raises ValueError.

    Asserts the error message mentions the offending edge and asks
    the user to remove one of the two declarations.
    """
    cfg: Dict[str, Any] = {
        "nodes": [
            _internal_node(
                "feed",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _internal_node(
                "r1",
                "IdealGasReactor",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
                volume=1e-5,
                inlet={"from": "feed", "mass_flow_rate": 1e-4},
            ),
        ],
        "connections": [
            _internal_conn(
                "feed_to_r1", "MassFlowController", "feed", "r1", mass_flow_rate=2e-4
            ),
        ],
    }
    with pytest.raises(ValueError, match="Inlet port on node 'r1'"):
        expand_port_shortcuts(cfg)


@pytest.mark.unit
def test_outlet_port_conflicts_with_explicit_connection() -> None:
    """Outlet port + explicit connection on the same edge raises ValueError.

    Asserts that declaring both an outlet: {to: sink} property and an
    explicit connection from the same source to the same target trips
    the duplicate-edge guard.
    """
    cfg: Dict[str, Any] = {
        "nodes": [
            _internal_node(
                "feed",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _internal_node(
                "r1",
                "IdealGasReactor",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
                volume=1e-5,
                inlet={"from": "feed", "mass_flow_rate": 1e-4},
                outlet={"to": "sink"},
            ),
            _internal_node(
                "sink",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
        ],
        "connections": [
            _internal_conn(
                "r1_to_sink", "MassFlowController", "r1", "sink", mass_flow_rate=1e-4
            ),
        ],
    }
    with pytest.raises(ValueError, match="Outlet port on node 'r1'"):
        expand_port_shortcuts(cfg)


@pytest.mark.unit
def test_outlet_port_multi_inlet_ambiguity_raises() -> None:
    """Default PC outlet on a 2-inlet reactor refuses to guess a master.

    Builds a mixer reactor with two explicit MFC inlets plus a default
    outlet: {to: sink} property. Because two candidate masters exist,
    expand_port_shortcuts must raise and list both candidates.
    """
    cfg: Dict[str, Any] = {
        "nodes": [
            _internal_node(
                "a",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _internal_node(
                "b",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _internal_node(
                "mixer",
                "IdealGasReactor",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
                volume=1e-5,
                outlet={"to": "sink"},
            ),
            _internal_node(
                "sink",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
        ],
        "connections": [
            _internal_conn(
                "a_to_mixer", "MassFlowController", "a", "mixer", mass_flow_rate=1e-4
            ),
            _internal_conn(
                "b_to_mixer", "MassFlowController", "b", "mixer", mass_flow_rate=2e-4
            ),
        ],
    }
    with pytest.raises(ValueError, match="ambiguous"):
        expand_port_shortcuts(cfg)


@pytest.mark.unit
def test_outlet_port_multi_inlet_explicit_master_resolves() -> None:
    """Ambiguity goes away when master: is set explicitly in the outlet port.

    Asserts the outlet expands to PressureController with the user-chosen
    master, and no error is raised.
    """
    cfg: Dict[str, Any] = {
        "nodes": [
            _internal_node(
                "a",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _internal_node(
                "b",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _internal_node(
                "mixer",
                "IdealGasReactor",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
                volume=1e-5,
                outlet={"to": "sink", "master": "a_to_mixer"},
            ),
            _internal_node(
                "sink",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
        ],
        "connections": [
            _internal_conn(
                "a_to_mixer", "MassFlowController", "a", "mixer", mass_flow_rate=1e-4
            ),
            _internal_conn(
                "b_to_mixer", "MassFlowController", "b", "mixer", mass_flow_rate=2e-4
            ),
        ],
    }
    expand_port_shortcuts(cfg)
    pc = next(c for c in cfg["connections"] if c["id"] == "mixer_to_sink")
    assert pc["type"] == "PressureController"
    assert pc["properties"]["master"] == "a_to_mixer"
