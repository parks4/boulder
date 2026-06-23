"""Run-set size accounting for the Run Sweep API (scenario: ⊎ sweep:, no host import)."""

from __future__ import annotations

from boulder.api.routes.sweep import _run_set_size


def test_sweep_only_counts_cartesian():
    raw = {"sweep": {"T": {"values": [1, 2, 3]}, "P": {"values": [10, 20]}}}
    assert _run_set_size(raw) == 6  # 3 × 2


def test_scenario_only_counts_entries():
    raw = {"scenario": {"a": {}, "b": {}, "c": {}}}
    assert _run_set_size(raw) == 3


def test_union_not_cartesian():
    raw = {
        "sweep": {"T": {"values": [1, 2]}},
        "scenario": {"hot": {}, "cold": {}},
    }
    # 2 global sweep points + 2 scenarios = 4 (not 2×2).
    assert _run_set_size(raw) == 4


def test_scenario_local_sweep_multiplies_only_itself():
    raw = {
        "scenario": {
            "plain": {},
            "swept": {"sweep": {"T": {"values": [1, 2, 3]}}},
        }
    }
    # plain (1) + swept's inner sweep (3) = 4.
    assert _run_set_size(raw) == 4


def test_empty_is_zero():
    assert _run_set_size({}) == 0
