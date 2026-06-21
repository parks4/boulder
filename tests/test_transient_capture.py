"""Solve-once transient trajectory capture for a live Run Simulation.

The staged ``advance_grid`` solve steps the reactor through every grid time; a
full-state recorder captures those steps (via the existing record() hook), so the
GUI shows the real T(t) without any re-integration — the network is solved once.
"""

from __future__ import annotations

import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config

REACTOR = {
    "id": "reactor",
    "IdealGasConstPressureMoleReactor": {
        "energy": "on",
        "initial": {
            "temperature": "1400 K",
            "pressure": "1 atm",
            "composition": "CH4:1, O2:2, N2:7.52",
        },
    },
}


def _config(solver: dict) -> dict:
    return normalize_config(
        {
            "phases": {"gas": {"mechanism": "gri30.yaml"}},
            "settings": {"solver": solver},
            "network": [REACTOR],
        }
    )


def _run(config: dict, sim_time: float, step: float) -> dict:
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    conv.build_network(config)
    results, _ = conv.run_streaming_simulation(
        simulation_time=sim_time, time_step=step, config=config
    )
    return results


def test_transient_run_yields_multipoint_trajectory():
    # Fine grid that straddles the ignition delay (ignition < 50 ms at 1400 K).
    config = _config({"kind": "advance_grid", "grid": {"start": 0.0, "stop": 0.1, "dt": 0.002}})
    results = _run(config, 0.1, 0.002)
    s = results["reactors"]["reactor"]
    assert len(s["T"]) > 5  # a real T(t), not a single converged point
    assert len(s["t"]) == len(s["T"])
    assert s.get("is_residence") is True
    # The ignition rise is captured across the checkpoints (pre- to post-ignition).
    assert max(s["T"]) - min(s["T"]) > 100.0
    assert max(s["T"]) > 2000.0  # reacted


def test_steady_run_stays_single_point():
    config = _config({"kind": "advance_to_steady_state"})
    results = _run(config, 1.0, 0.1)
    # No transient stepping → recorder empty → the converged snapshot is kept.
    assert len(results["reactors"]["reactor"]["T"]) == 1


def test_recorder_present_only_records_when_transient():
    """The recorder is installed but captures nothing for a steady solve."""
    config = _config({"kind": "advance_to_steady_state"})
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    conv.build_network(config)
    assert conv._trajectory_recorder is not None
    assert conv._trajectory_recorder.series() == {}
