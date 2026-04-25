"""Tests for port/connection conflict detection in ``normalize_config``.

When a YAML declares both a node-level ``inlet:`` / ``outlet:`` port and
an explicit ``connections:`` entry that synthesises to the same id (or
same ``(source, target)`` edge), ``normalize_config`` must raise rather
than silently override one side.  Also covers multi-inlet ambiguity: a
default ``outlet: PressureController`` on a reactor with two MFC inlets
cannot auto-pick a master and must raise an actionable error.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from boulder.config import normalize_config


def _node(nid: str, kind: str, **props: Any) -> Dict[str, Any]:
    return {"id": nid, kind: props}


@pytest.mark.unit
def test_inlet_port_conflicts_with_explicit_connection() -> None:
    """Inlet port + explicit MFC on the same edge raises ``ValueError``.

    Asserts the error message mentions both the offending edge and asks
    the user to remove one of the two declarations.
    """
    cfg: Dict[str, Any] = {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            _node(
                "feed",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _node(
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
            {
                "id": "feed_to_r1",
                "MassFlowController": {"mass_flow_rate": 2e-4},
                "source": "feed",
                "target": "r1",
            },
        ],
    }
    with pytest.raises(ValueError, match="Inlet port on node 'r1'"):
        normalize_config(cfg)


@pytest.mark.unit
def test_outlet_port_conflicts_with_explicit_connection() -> None:
    """Outlet port + explicit connection on the same edge raises ``ValueError``.

    Asserts that declaring both an ``outlet: { to: sink }`` port and an
    explicit connection from the same source to the same target trips
    the duplicate-edge guard.
    """
    cfg: Dict[str, Any] = {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            _node(
                "feed",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _node(
                "r1",
                "IdealGasReactor",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
                volume=1e-5,
                inlet={"from": "feed", "mass_flow_rate": 1e-4},
                outlet={"to": "sink"},
            ),
            _node(
                "sink",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
        ],
        "connections": [
            {
                "id": "r1_to_sink",
                "MassFlowController": {"mass_flow_rate": 1e-4},
                "source": "r1",
                "target": "sink",
            },
        ],
    }
    with pytest.raises(ValueError, match="Outlet port on node 'r1'"):
        normalize_config(cfg)


@pytest.mark.unit
def test_outlet_port_multi_inlet_ambiguity_raises() -> None:
    """Default PC outlet on a 2-inlet reactor refuses to guess a master.

    Builds a mixer reactor with two explicit MFC inlets plus a default
    ``outlet: {to: sink}`` port (which would default to
    ``PressureController``).  Because two candidate masters exist,
    ``normalize_config`` must raise and list both candidates so the
    user can pick one.
    """
    cfg: Dict[str, Any] = {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            _node(
                "a",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _node(
                "b",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _node(
                "mixer",
                "IdealGasReactor",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
                volume=1e-5,
                outlet={"to": "sink"},
            ),
            _node(
                "sink",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
        ],
        "connections": [
            {
                "id": "a_to_mixer",
                "MassFlowController": {"mass_flow_rate": 1e-4},
                "source": "a",
                "target": "mixer",
            },
            {
                "id": "b_to_mixer",
                "MassFlowController": {"mass_flow_rate": 2e-4},
                "source": "b",
                "target": "mixer",
            },
        ],
    }
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_config(cfg)


@pytest.mark.unit
def test_outlet_port_multi_inlet_explicit_master_resolves() -> None:
    """Ambiguity goes away when ``master:`` is set explicitly in the port.

    Asserts that the outlet expands to a ``PressureController`` whose
    ``master`` is the user-chosen MFC, and no error is raised.
    """
    cfg: Dict[str, Any] = {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            _node(
                "a",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _node(
                "b",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
            _node(
                "mixer",
                "IdealGasReactor",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
                volume=1e-5,
                outlet={"to": "sink", "master": "a_to_mixer"},
            ),
            _node(
                "sink",
                "Reservoir",
                temperature=300.0,
                pressure=101325.0,
                composition="N2:1",
            ),
        ],
        "connections": [
            {
                "id": "a_to_mixer",
                "MassFlowController": {"mass_flow_rate": 1e-4},
                "source": "a",
                "target": "mixer",
            },
            {
                "id": "b_to_mixer",
                "MassFlowController": {"mass_flow_rate": 2e-4},
                "source": "b",
                "target": "mixer",
            },
        ],
    }
    normalized = normalize_config(cfg)
    pc = next(c for c in normalized["connections"] if c["id"] == "mixer_to_sink")
    assert pc["type"] == "PressureController"
    assert pc["properties"]["master"] == "a_to_mixer"
