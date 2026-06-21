"""The live transient trajectory capture (single-reactor Run Simulation)."""

from __future__ import annotations

from boulder.cantera_converter import DualCanteraConverter

NODE = {
    "id": "reactor",
    "type": "IdealGasConstPressureMoleReactor",
    "properties": {
        "energy": "on",
        "initial": {
            "temperature": "1400 K",
            "pressure": "1 atm",
            "composition": "CH4:1, O2:2, N2:7.52",
        },
    },
}


def _converter_with_reactor():
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    conv.build_isolated_reactor(NODE)  # populates conv.reactors["reactor"]
    return conv


def test_capture_linear_grid_multipoint():
    conv = _converter_with_reactor()
    config = {
        "nodes": [NODE],
        "settings": {"solver": {"grid": {"start": 0.0, "stop": 0.5, "dt": 0.05}}},
    }
    traj = conv._capture_transient_trajectory(config)
    assert traj is not None
    s = traj["reactor"]
    assert len(s["T"]) > 5  # a real trajectory, not a single point
    assert len(s["t"]) == len(s["T"]) == len(s["P"])
    assert s["is_residence"] is True
    assert "CH4" in s["X"] and len(s["X"]["CH4"]) == len(s["T"])
    # Ignition: temperature must rise across the window.
    assert s["T"][-1] > s["T"][0] + 100.0


def test_capture_explicit_list_grid():
    conv = _converter_with_reactor()
    config = {"nodes": [NODE], "settings": {"solver": {"grid": [0.01, 0.1, 0.5, 1.0]}}}
    traj = conv._capture_transient_trajectory(config)
    assert traj is not None
    # t0 sample + the 4 grid points.
    assert len(traj["reactor"]["t"]) == 5


def test_no_grid_returns_none():
    conv = _converter_with_reactor()
    assert conv._capture_transient_trajectory({"nodes": [NODE], "settings": {}}) is None


def test_isolation_throwaway_converter():
    """Capture must not perturb the caller converter's reactor/network state."""
    conv = _converter_with_reactor()
    before = conv.reactors["reactor"].phase.T
    conv._capture_transient_trajectory(
        {"nodes": [NODE], "settings": {"solver": {"grid": {"stop": 0.5, "dt": 0.1}}}}
    )
    assert conv.reactors["reactor"].phase.T == before  # untouched
