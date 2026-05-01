"""Tests for terminal-OutletSink pressure defaulting in normalize_config.

``propagate_terminal_pressure_defaults`` runs after composite expansion and
before connection master sorting.  It groups nodes by flow-connectivity
(excluding Wall edges) and, within each component that has exactly one
declared pressure, fills missing ``properties.pressure`` values on all
other nodes in that component.

Asserts:
1. A staged chain where only the terminal OutletSink declares a pressure
   propagates that value to all upstream process nodes missing a pressure.
2. An ambient Reservoir connected only via a Wall edge is NOT reached by
   the propagation (stays at its own declared pressure).
3. Two nodes in the same flow-connected component with *different* declared
   pressures raise a clear ValueError.
4. When every node already has a pressure, nothing is overwritten
   (backward-compatible with existing configs).
"""

from __future__ import annotations

import pytest

from boulder.config import normalize_config

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_GRI = "gri30.yaml"


def _base() -> dict:
    return {"phases": {"gas": {"mechanism": _GRI}}}


# ---------------------------------------------------------------------------
# 1. Pressure propagates from OutletSink to upstream nodes that lack pressure
# ---------------------------------------------------------------------------


def test_process_pressure_propagates_from_outlet_sink_to_upstream_nodes():
    """Single flow-connected component: OutletSink declares 1.3 bar;
    upstream Reservoir has no pressure; after normalize_config the Reservoir
    must carry 1.3 bar (130 000 Pa after unit coercion).
    """
    cfg = {
        **_base(),
        "network": [
            {
                "id": "feed",
                "Reservoir": {
                    "temperature": 300.0,
                    "composition": "N2:1",
                    # no pressure declared — should be filled
                },
            },
            {
                "id": "reactor",
                "IdealGasConstPressureMoleReactor": {
                    "volume": 1e-4,
                    # no pressure declared — should be filled
                },
            },
            {
                "id": "sink",
                "OutletSink": {
                    "pressure": "1.3 bar",
                },
            },
            {
                "id": "feed_mfc",
                "MassFlowController": {"mass_flow_rate": 1e-3},
                "source": "feed",
                "target": "reactor",
            },
            {
                "id": "reactor_out",
                "MassFlowController": {},
                "source": "reactor",
                "target": "sink",
            },
        ],
    }
    norm = normalize_config(cfg)
    node_pressures = {n["id"]: n["properties"].get("pressure") for n in norm["nodes"]}
    expected_pa = pytest.approx(130_000.0, rel=1e-4)
    assert node_pressures["sink"] == expected_pa, "OutletSink pressure not set"
    assert node_pressures["feed"] == expected_pa, "Reservoir pressure not propagated"
    assert node_pressures["reactor"] == expected_pa, "Reactor pressure not propagated"


# ---------------------------------------------------------------------------
# 2. Ambient Reservoir connected only via Wall is NOT reached
# ---------------------------------------------------------------------------


def test_ambient_reservoir_connected_only_via_wall_keeps_its_own_pressure():
    """The pfr_ambient Reservoir is connected to the process via a Wall only.
    It must NOT receive the process pressure (1.3 bar); it keeps 101 325 Pa.
    """
    cfg = {
        **_base(),
        "network": [
            {
                "id": "feed",
                "Reservoir": {
                    "temperature": 300.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "reactor",
                "IdealGasConstPressureMoleReactor": {
                    "volume": 1e-4,
                },
            },
            {
                "id": "ambient",
                "Reservoir": {
                    "temperature": 298.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "sink",
                "OutletSink": {
                    "pressure": "1.3 bar",
                },
            },
            # flow edges (process path)
            {
                "id": "feed_mfc",
                "MassFlowController": {"mass_flow_rate": 1e-3},
                "source": "feed",
                "target": "reactor",
            },
            {
                "id": "reactor_out",
                "MassFlowController": {},
                "source": "reactor",
                "target": "sink",
            },
            # Wall edge — must not carry pressure propagation
            {
                "id": "loss_wall",
                "Wall": {"area": 1.0},
                "source": "ambient",
                "target": "reactor",
            },
        ],
    }
    norm = normalize_config(cfg)
    node_pressures = {n["id"]: n["properties"].get("pressure") for n in norm["nodes"]}
    # ambient must remain at 1 atm
    assert node_pressures["ambient"] == pytest.approx(101325.0, rel=1e-4)
    # process nodes still get 1.3 bar
    assert node_pressures["sink"] == pytest.approx(130_000.0, rel=1e-4)
    assert node_pressures["feed"] == pytest.approx(130_000.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 3. Conflicting pressures in the same flow-connected component → ValueError
# ---------------------------------------------------------------------------


def test_conflicting_process_pressures_raise_value_error():
    """Two nodes in the same flow-connected component declare different
    pressures (1.3 bar vs 1.0 bar).  normalize_config must raise ValueError
    with a message that names both nodes.
    """
    cfg = {
        **_base(),
        "network": [
            {
                "id": "feed",
                "Reservoir": {
                    "temperature": 300.0,
                    "composition": "N2:1",
                    "pressure": "1.0 bar",
                },
            },
            {
                "id": "sink",
                "OutletSink": {
                    "pressure": "1.3 bar",
                },
            },
            {
                "id": "feed_mfc",
                "MassFlowController": {"mass_flow_rate": 1e-3},
                "source": "feed",
                "target": "sink",
            },
        ],
    }
    with pytest.raises(ValueError, match="pressure"):
        normalize_config(cfg)


# ---------------------------------------------------------------------------
# 4. When every node already has a pressure, nothing is changed
# ---------------------------------------------------------------------------


def test_existing_pressures_not_overwritten_when_consistent():
    """If every node already carries the same pressure value, the defaulting
    pass leaves them all intact — backward-compatible with old configs.
    """
    cfg = {
        **_base(),
        "network": [
            {
                "id": "feed",
                "Reservoir": {
                    "temperature": 300.0,
                    "composition": "N2:1",
                    "pressure": "1.3 bar",
                },
            },
            {
                "id": "sink",
                "OutletSink": {
                    "pressure": "1.3 bar",
                },
            },
            {
                "id": "feed_mfc",
                "MassFlowController": {"mass_flow_rate": 1e-3},
                "source": "feed",
                "target": "sink",
            },
        ],
    }
    norm = normalize_config(cfg)
    node_pressures = {n["id"]: n["properties"].get("pressure") for n in norm["nodes"]}
    assert node_pressures["feed"] == pytest.approx(130_000.0, rel=1e-4)
    assert node_pressures["sink"] == pytest.approx(130_000.0, rel=1e-4)
