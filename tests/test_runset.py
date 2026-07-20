"""Unit tests for :mod:`boulder.runset` — the scenarios:/sweep: reference implementation.

Ported from the host package that pioneered the semantics, so the union rules,
id naming, and error messages stay locked while living upstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boulder.runset import (
    deep_merge,
    expand_scenarios,
    load_yaml_with_inheritance,
    run_set_size,
    sweep_axis_values,
)

# ---------------------------------------------------------------------------
# expand_scenarios
# ---------------------------------------------------------------------------


def test_expand_scenarios_no_block_returns_single_base():
    """A YAML without scenarios:/sweep: yields a single scenario.

    whose id matches ``metadata.scenario_id``.
    """
    base = {"metadata": {"scenario_id": "MY_BASE"}, "nodes": []}
    out = expand_scenarios(base)
    assert len(out) == 1
    sid, cfg = out[0]
    assert sid == "MY_BASE"
    assert "scenarios" not in cfg
    assert "sweeps" not in cfg


def test_expand_scenarios_legacy_scenarios_list_raises_migration_error():
    """The pre-2026-06 ``scenarios:`` (list) schema fails loudly, not silently.

    A config carrying the legacy key must raise an actionable migration error
    instead of expanding to just the base (which would silently drop every
    variant and later fail downstream on an unknown top-level key).
    """
    base = {
        "metadata": {"scenario_id": "BASE"},
        "scenarios": [{"id": "old_style", "set": {"metadata": {"x": 1}}}],
    }
    with pytest.raises(ValueError, match="no longer supported.*mapping form"):
        expand_scenarios(base)


def test_expand_scenario_mapping_deep_merges_overlays():
    """Deep-merge each `scenarios:` overlay onto the base.

    The key is the scenario id; id-keyed lists (``nodes``) merge by id.
    """
    base = {
        "metadata": {"scenario_id": "BASE"},
        "nodes": [{"id": "torch", "properties": {"T_out": 2500}}],
        "scenarios": {
            "hot": {"nodes": [{"id": "torch", "properties": {"T_out": 3000}}]},
            "cold": {"nodes": [{"id": "torch", "properties": {"T_out": 2000}}]},
        },
    }
    out = expand_scenarios(base)
    # BASELINE (the unmodified base) is always first when scenarios: is declared.
    assert [sid for sid, _ in out] == ["BASELINE", "hot", "cold"]
    assert out[0][1]["nodes"][0]["properties"]["T_out"] == 2500
    assert out[1][1]["nodes"][0]["properties"]["T_out"] == 3000
    assert out[2][1]["nodes"][0]["properties"]["T_out"] == 2000
    assert out[0][1]["metadata"]["scenario_id"] == "BASELINE"
    assert out[1][1]["metadata"]["scenario_id"] == "hot"
    assert "scenarios" not in out[0][1]


def test_expand_scenario_plus_global_sweep_is_union_not_cartesian():
    """Top-level sweep + scenarios run as a union (M+N), not a cross product."""
    base = {
        "metadata": {"scenario_id": "BASE"},
        "nodes": [{"id": "torch", "properties": {"T_out": 2500}}],
        "sweep": {
            "T": {"path": "nodes[id=torch].properties.T_out", "values": [2600, 2700]}
        },
        "scenarios": {
            "hot": {"nodes": [{"id": "torch", "properties": {"T_out": 3000}}]},
        },
    }
    out = expand_scenarios(base)
    ids = [sid for sid, _ in out]
    # BASELINE + 2 global sweep points + 1 scenario = 4 (not a cross product).
    assert ids == ["BASELINE", "BASE__T=2600", "BASE__T=2700", "hot"]


def test_expand_scenario_local_sweep_multiplies_only_that_scenario():
    """A `sweep:` inside one scenario expands that scenario only."""
    base = {
        "metadata": {"scenario_id": "BASE"},
        "nodes": [{"id": "torch", "properties": {"T_out": 2500}}],
        "scenarios": {
            "plain": {"nodes": [{"id": "torch", "properties": {"T_out": 2000}}]},
            "swept": {
                "sweep": {
                    "T": {
                        "path": "nodes[id=torch].properties.T_out",
                        "values": [2800, 2900],
                    }
                }
            },
        },
    }
    out = expand_scenarios(base)
    assert [sid for sid, _ in out] == [
        "BASELINE",
        "plain",
        "swept__T=2800",
        "swept__T=2900",
    ]
    swept = {sid: cfg for sid, cfg in out}
    assert swept["swept__T=2800"]["nodes"][0]["properties"]["T_out"] == 2800


def test_expand_scenarios_sweep_with_id_selector_targets_list_element():
    """A sweep path with ``[id=...]`` selector overrides one element.

    A single element inside an id-keyed list is patched instead of the list
    being replaced.
    """
    base = {
        "metadata": {"scenario_id": "S"},
        "nodes": [
            {"id": "torch", "properties": {"T_out": 2500}},
            {"id": "psr", "properties": {"volume": 1e-3}},
        ],
        "sweeps": {
            "T": {
                "path": "nodes[id=torch].properties.T_out",
                "values": [2500, 3000],
            },
        },
    }
    out = expand_scenarios(base)
    assert len(out) == 2
    t_values = [cfg["nodes"][0]["properties"]["T_out"] for _, cfg in out]
    assert t_values == [2500, 3000]
    # psr node must be preserved across sweep points
    for _, cfg in out:
        assert cfg["nodes"][1]["properties"]["volume"] == 1e-3


def test_expand_scenarios_sweep_min_max_num_expands_like_values():
    """A `min`/`max`/`num` sweep expands to the same scenarios as an explicit list."""
    base = {
        "metadata": {"scenario_id": "BASE"},
        "network": [{"id": "r", "Foo": {"t": 0}}],
        "sweeps": {
            "t": {
                "path": "network[id=r].Foo.t",
                "min": 0.0,
                "max": 10.0,
                "num": 3,
            }
        },
    }
    out = expand_scenarios(base)
    assert len(out) == 3
    temps = [cfg["network"][0]["Foo"]["t"] for _sid, cfg in out]
    assert temps == [0.0, 5.0, 10.0]


def test_expand_scenarios_sweep_malformed_axis_raises():
    """A sweep axis missing 'path' or 'values' raises ValueError."""
    base = {"metadata": {"scenario_id": "S"}, "sweeps": {"T": {"path": "x"}}}
    with pytest.raises(ValueError, match="must be a dict with 'path'"):
        expand_scenarios(base)


def test_expand_scenarios_sweep_uses_symbols_mapping_for_axis_labels():
    """Sweep ids use the host symbol mapping instead of raw axis names.

    The ``symbols`` hook (or the registered ``plugins.sweep_symbols``) maps the
    path leaf / axis name to the symbol used in scenario ids.
    """
    base = {
        "metadata": {"scenario_id": "BASE"},
        "sweeps": {
            "diameter": {
                "path": "nodes[id=tube_furnace].TubeFurnace.diameter",
                "values": [0.03],
            }
        },
    }
    out = expand_scenarios(base, symbols={"diameter": "TF_D"})
    assert len(out) == 1
    assert out[0][0] == "BASE__TF_D=0.03"


def test_expand_scenarios_sweep_prefers_explicit_symbol_override():
    """An axis ``symbol:`` override wins over the symbols mapping."""
    base = {
        "metadata": {"scenario_id": "BASE"},
        "sweeps": {
            "diameter": {
                "path": "nodes[id=tube_furnace].TubeFurnace.diameter",
                "values": [0.03],
                "symbol": "MY_D",
            }
        },
    }
    out = expand_scenarios(base, symbols={"diameter": "TF_D"})
    assert len(out) == 1
    assert out[0][0] == "BASE__MY_D=0.03"


# ---------------------------------------------------------------------------
# sweep_axis_values
# ---------------------------------------------------------------------------


def test_sweep_axis_values_error_paths():
    """Malformed range specs raise ValueError with actionable messages."""
    with pytest.raises(ValueError, match="requires 'num'"):
        sweep_axis_values({"min": 0.0, "max": 1.0})
    with pytest.raises(ValueError, match="must be >= 1"):
        sweep_axis_values({"min": 0.0, "max": 1.0, "num": 0})
    with pytest.raises(ValueError, match="positive 'min' and 'max'"):
        sweep_axis_values({"min": 0.0, "max": 1.0, "num": 3, "spacing": "log"})
    with pytest.raises(ValueError, match="unknown sweep spacing"):
        sweep_axis_values({"min": 0.0, "max": 1.0, "num": 3, "spacing": "lgo"})


def test_sweep_axis_values_min_max_num_matches_explicit_list():
    """`min`/`max`/`num` generates the same evenly spaced list as an explicit one."""
    generated = sweep_axis_values({"min": 1273.15, "max": 2573.15, "num": 21})
    expected = [1273.15 + 65.0 * i for i in range(21)]
    assert generated == pytest.approx(expected)
    assert generated[0] == 1273.15 and generated[-1] == 2573.15


def test_sweep_axis_values_log_spacing():
    """`spacing: log` yields a geometric series across the range."""
    assert sweep_axis_values(
        {"min": 1e-4, "max": 10.0, "num": 6, "spacing": "log"}
    ) == pytest.approx([1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0])


# ---------------------------------------------------------------------------
# run_set_size — must agree with expand_scenarios
# ---------------------------------------------------------------------------


def test_run_set_size_counts_min_max_num_ranges():
    """Range-form axes count by their generated length (the old mirror guessed)."""
    raw = {
        "sweep": {
            "T": {"path": "metadata.x", "min": 0.0, "max": 10.0, "num": 5},
            "P": {"path": "metadata.y", "values": [1, 2]},
        }
    }
    assert run_set_size(raw) == 10  # 5 × 2


def test_run_set_size_matches_expand_scenarios():
    """The cheap count and the real expansion agree on the union semantics."""
    raw = {
        "metadata": {"scenario_id": "BASE"},
        "sweep": {"T": {"path": "metadata.t", "values": [1, 2]}},
        "scenarios": {
            "plain": {},
            "swept": {"sweep": {"P": {"path": "metadata.p", "values": [3, 4, 5]}}},
        },
    }
    assert (
        run_set_size(raw) == len(expand_scenarios(raw)) == 7
    )  # 1 (BASELINE) ⊎ 2 ⊎ (1 + 3)


def test_run_set_size_malformed_axis_counts_zero():
    """Sizing never raises — malformed axes count 0 (expansion fails loudly)."""
    assert run_set_size({"sweep": {"T": {"min": 0.0, "max": 1.0}}}) == 0


# ---------------------------------------------------------------------------
# deep_merge / load_yaml_with_inheritance
# ---------------------------------------------------------------------------


def test_deep_merge_id_keyed_lists_merge_by_id():
    """Lists of dicts that all carry ``id`` merge element-wise, not wholesale."""
    base = {
        "nodes": [
            {"id": "a", "properties": {"x": 1, "y": 2}},
            {"id": "b", "properties": {"x": 3}},
        ]
    }
    overlay = {"nodes": [{"id": "a", "properties": {"x": 10}}]}
    merged = deep_merge(base, overlay)
    assert merged["nodes"][0]["properties"] == {"x": 10, "y": 2}
    assert merged["nodes"][1] == {"id": "b", "properties": {"x": 3}}


def test_deep_merge_plain_lists_replace():
    """Lists without ids are replaced by the overlay, not concatenated."""
    assert deep_merge({"v": [1, 2, 3]}, {"v": [9]}) == {"v": [9]}


def test_load_yaml_with_inheritance_sweeps_inherited_scenario_not(tmp_path: Path):
    """``sweep:`` is inherited through ``from:``; ``scenarios:`` is not.

    A parent's named run-set must not leak into a child overlay, but a child
    legitimately re-runs the parent's parameter sweep with overrides.
    """
    parent = tmp_path / "parent.yaml"
    parent.write_text(
        "metadata: {scenario_id: PARENT}\n"
        "sweep:\n"
        "  T: {path: metadata.t, values: [1, 2]}\n"
        "scenarios:\n"
        "  variant_a: {metadata: {x: 1}}\n",
        encoding="utf-8",
    )
    child = tmp_path / "child.yaml"
    child.write_text(
        "from: parent.yaml\nmetadata: {scenario_id: CHILD}\n", encoding="utf-8"
    )
    cfg = load_yaml_with_inheritance(child)
    assert cfg["metadata"]["scenario_id"] == "CHILD"
    assert "scenarios" not in cfg
    assert cfg["sweep"]["T"]["values"] == [1, 2]
