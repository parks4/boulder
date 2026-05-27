"""Unit tests for boulder.export.points_from_streams.

Asserts:
- Stream-point nodes (stream_point: true in properties) are extracted.
- Non-stream-point nodes are ignored.
- Derived fields (T_C, P_bar, h_mass_J_kg) are correctly computed.
- target_nodes is resolved from node properties when present.
- target_nodes falls back to scanning connections when not in properties.
- An empty list is returned when no stream points are present.
"""

from __future__ import annotations

from boulder.export import points_from_streams


def _config(*nodes, connections=None):
    return {"nodes": list(nodes), "connections": connections or []}


def _sp_node(
    nid: str = "psr_outlet",
    T: float = 1273.15,
    P: float = 2e5,
    mdot: float = 0.5,
    target_nodes: list | None = None,
):
    return {
        "id": nid,
        "properties": {
            "stream_point": True,
            "temperature": T,
            "pressure": P,
            "mdot": mdot,
            "h_mass": -1_200_000.0,
            "density": 0.3,
            "v_dot_normal_m3_h": 12.0,
            "v_dot_real_m3_h": 6.0,
            "top_Y": {"H2": 0.32, "CO": 0.18, "N2": 0.50},
            "target_nodes": target_nodes or ["pfr"],
        },
    }


def _reactor_node(nid: str = "psr"):
    return {"id": nid, "properties": {"reactor_kind": "PSR"}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_config_returns_empty_list():
    """points_from_streams returns [] for a config with no nodes."""
    assert points_from_streams({}) == []


def test_no_stream_points_returns_empty():
    """Non-stream-point nodes are ignored; empty list returned."""
    cfg = _config(_reactor_node("psr"), _reactor_node("pfr"))
    assert points_from_streams(cfg) == []


def test_extracts_one_stream_point():
    """A single stream-point node produces one entry in the output."""
    cfg = _config(_sp_node())
    pts = points_from_streams(cfg)
    assert len(pts) == 1
    assert pts[0]["id"] == "psr_outlet"


def test_temperature_kelvin_and_celsius():
    """T_K and T_C are correctly populated from the 'temperature' property."""
    cfg = _config(_sp_node(T=1273.15))
    pts = points_from_streams(cfg)
    assert pts[0]["T_K"] == 1273.15
    assert abs(pts[0]["T_C"] - 1000.0) < 0.01


def test_pressure_pa_and_bar():
    """P_Pa and P_bar are correctly derived from the 'pressure' property."""
    cfg = _config(_sp_node(P=3e5))
    pts = points_from_streams(cfg)
    assert pts[0]["P_Pa"] == 3e5
    assert abs(pts[0]["P_bar"] - 3.0) < 1e-9


def test_target_nodes_from_properties():
    """target_nodes is taken from node properties when available."""
    cfg = _config(_sp_node(target_nodes=["pfr", "afterburner"]))
    pts = points_from_streams(cfg)
    assert set(pts[0]["target_nodes"]) == {"pfr", "afterburner"}


def test_target_nodes_fallback_to_connections():
    """target_nodes falls back to scanning connections when absent in properties."""
    node = {
        "id": "psr_outlet",
        "properties": {"stream_point": True, "temperature": 1000.0, "pressure": 1e5},
    }
    connections = [
        {"source": "psr_outlet", "target": "pfr"},
        {"source": "psr", "target": "psr_outlet"},  # should be ignored
    ]
    cfg = _config(node, connections=connections)
    pts = points_from_streams(cfg)
    assert pts[0]["target_nodes"] == ["pfr"]


def test_multiple_stream_points():
    """Multiple stream-point diamonds all appear in output, in config order."""
    cfg = _config(_sp_node("torch_outlet", T=2500.0), _sp_node("psr_outlet", T=1273.15))
    pts = points_from_streams(cfg)
    assert len(pts) == 2
    assert pts[0]["id"] == "torch_outlet"
    assert pts[1]["id"] == "psr_outlet"


def test_mixed_nodes_only_stream_points_extracted():
    """Only stream-point nodes are extracted; reactor nodes are skipped."""
    cfg = _config(
        _reactor_node("torch"),
        _sp_node("torch_outlet"),
        _reactor_node("psr"),
        _sp_node("psr_outlet"),
        _reactor_node("pfr"),
    )
    pts = points_from_streams(cfg)
    assert len(pts) == 2
    ids = {p["id"] for p in pts}
    assert ids == {"torch_outlet", "psr_outlet"}


def test_top_Y_extracted():
    """top_Y dict is correctly extracted from node properties."""
    cfg = _config(_sp_node())
    pts = points_from_streams(cfg)
    assert pts[0]["top_Y"] == {"H2": 0.32, "CO": 0.18, "N2": 0.50}
