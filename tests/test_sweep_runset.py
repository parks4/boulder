"""Run-set size accounting for the Run Sweep API (scenarios: ⊎ sweep:, no host import)."""

from __future__ import annotations

from pathlib import Path

from boulder.api.routes.sweep import _run_set_size, has_run_set, resolve_store_path


def test_sweep_only_counts_cartesian():
    raw = {"sweep": {"T": {"values": [1, 2, 3]}, "P": {"values": [10, 20]}}}
    assert _run_set_size(raw) == 6  # 3 × 2


def test_scenario_only_counts_entries():
    raw = {"scenarios": {"a": {}, "b": {}, "c": {}}}
    # BASELINE (the unmodified base) + 3 named entries = 4.
    assert _run_set_size(raw) == 4


def test_union_not_cartesian():
    raw = {
        "sweep": {"T": {"values": [1, 2]}},
        "scenarios": {"hot": {}, "cold": {}},
    }
    # BASELINE + 2 global sweep points + 2 scenarios = 5 (not a cross product).
    assert _run_set_size(raw) == 5


def test_scenario_local_sweep_multiplies_only_itself():
    raw = {
        "scenarios": {
            "plain": {},
            "swept": {"sweep": {"T": {"values": [1, 2, 3]}}},
        }
    }
    # BASELINE (1) + plain (1) + swept's inner sweep (3) = 5.
    assert _run_set_size(raw) == 5


def test_empty_is_zero():
    assert _run_set_size({}) == 0


def test_has_run_set_true_for_scenario_block():
    assert has_run_set({"scenarios": {"a": {}}}, None) is True


def test_has_run_set_true_for_sweep_block():
    assert has_run_set({"sweep": {"T": {"values": [1]}}}, None) is True
    assert has_run_set({"sweeps": {"T": {"values": [1]}}}, None) is True


def test_has_run_set_false_without_block_or_runner(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("metadata: {}\n", encoding="utf-8")
    assert has_run_set({}, str(cfg)) is False


def test_has_run_set_true_for_local_run_sweep_script(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("metadata: {}\n", encoding="utf-8")
    (tmp_path / "run_sweep.py").write_text("", encoding="utf-8")
    # No inline scenarios:/sweep: block at all — the local runner script alone
    # is enough (host-defined run-set, e.g. the CH4 reactor-map sandbox).
    assert has_run_set({}, str(cfg)) is True


def test_resolve_store_path_defaults_next_to_config(tmp_path: Path):
    cfg = tmp_path / "my_map.yaml"
    assert resolve_store_path({}, str(cfg)) == tmp_path / "my_map_scenarios.h5"


def test_resolve_store_path_honours_declared_relative_path(tmp_path: Path):
    cfg = tmp_path / "my_map.yaml"
    raw = {"metadata": {"extra": {"scenario_store": "results/store.h5"}}}
    assert resolve_store_path(raw, str(cfg)) == tmp_path / "results" / "store.h5"


def test_resolve_store_path_none_without_config_path():
    assert resolve_store_path({}, None) is None
