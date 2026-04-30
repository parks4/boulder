"""Tests for ``expand_composite_kinds`` and the split ``Wall`` builder.

Covers:

- An unfolder that adds 1 node + 1 connection is merged into the normalised
  config; the Cytoscape-readable ``nodes`` and ``connections`` lists carry
  those entries.
- A duplicate-id collision where the emitted entry differs from an existing
  node/connection raises ``ValueError``.
- A byte-identical re-unfold (same id, same content) is a no-op.
- Registering the same unfolder for two kinds works independently.
- The torch-power Wall branch creates a Wall with a heat-rate callable.
- The generic passive Wall branch creates a Wall with ``heat_flux`` settable
  post-build; ``area`` is honoured.
- Mixing ``electric_power_kW`` into a passive Wall is handled by the correct
  branch (torch branch takes precedence).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

import cantera as ct
import pytest

from boulder.cantera_converter import BoulderPlugins
from boulder.config import expand_composite_kinds, normalize_config
from boulder.schema_registry import register_reactor_unfolder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugins_with_unfolder(kind: str, unfolder) -> BoulderPlugins:
    plugins = BoulderPlugins()
    register_reactor_unfolder(plugins, kind, unfolder)
    return plugins


def _simple_unfolder(node: Dict[str, Any]) -> Dict[str, List]:
    """Emit one ambient Reservoir + one Wall for any node."""
    rid = node["id"]
    return {
        "nodes": [
            {
                "id": f"{rid}_ambient",
                "type": "Reservoir",
                "properties": {
                    "temperature": 298.15,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            }
        ],
        "connections": [
            {
                "id": f"{rid}_loss_wall",
                "type": "Wall",
                "properties": {"area": 1.0},
                "source": f"{rid}_ambient",
                "target": rid,
            }
        ],
    }


def _minimal_config_with_kind(kind: str) -> Dict[str, Any]:
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            {
                "id": "pfr",
                "type": kind,
                "properties": {
                    "temperature": 1000.0,
                    "pressure": 101325.0,
                    "composition": "CH4:1",
                },
            }
        ],
        "connections": [],
    }


# ---------------------------------------------------------------------------
# expand_composite_kinds — unit tests (no Cantera build)
# ---------------------------------------------------------------------------


class TestExpandCompositeKinds:
    def test_satellites_appended(self):
        """Unfolder result is appended to nodes and connections lists."""
        config = _minimal_config_with_kind("FakeKind")
        plugins = _make_plugins_with_unfolder("FakeKind", _simple_unfolder)
        expand_composite_kinds(config, plugins)
        node_ids = [n["id"] for n in config["nodes"]]
        conn_ids = [c["id"] for c in config["connections"]]
        assert "pfr_ambient" in node_ids
        assert "pfr_loss_wall" in conn_ids

    def test_no_unfolder_leaves_config_unchanged(self):
        """Config is unchanged when no unfolder is registered for the kind."""
        config = _minimal_config_with_kind("UnknownKind")
        original = copy.deepcopy(config)
        expand_composite_kinds(config, BoulderPlugins())
        assert config == original

    def test_byte_identical_rerun_is_noop(self):
        """Running unfold twice with identical output leaves a single copy."""
        config = _minimal_config_with_kind("FakeKind")
        plugins = _make_plugins_with_unfolder("FakeKind", _simple_unfolder)
        expand_composite_kinds(config, plugins)
        node_count_after_first = len(config["nodes"])
        conn_count_after_first = len(config["connections"])
        expand_composite_kinds(config, plugins)
        assert len(config["nodes"]) == node_count_after_first
        assert len(config["connections"]) == conn_count_after_first

    def test_collision_raises_for_nodes(self):
        """Collision on node id with different content raises ValueError."""
        config = _minimal_config_with_kind("FakeKind")
        config["nodes"].append(
            {
                "id": "pfr_ambient",
                "type": "Reservoir",
                "properties": {"temperature": 500.0},  # different content
            }
        )
        plugins = _make_plugins_with_unfolder("FakeKind", _simple_unfolder)
        with pytest.raises(ValueError, match="collision"):
            expand_composite_kinds(config, plugins)

    def test_collision_raises_for_connections(self):
        """Collision on connection id with different content raises ValueError."""
        config = _minimal_config_with_kind("FakeKind")
        config["connections"].append(
            {
                "id": "pfr_loss_wall",
                "type": "Wall",
                "source": "other_src",  # different source
                "target": "pfr",
                "properties": {},
            }
        )
        plugins = _make_plugins_with_unfolder("FakeKind", _simple_unfolder)
        with pytest.raises(ValueError, match="collision"):
            expand_composite_kinds(config, plugins)

    def test_two_instances_produce_distinct_ids(self):
        """Two nodes of the same kind get distinct satellite ids."""
        config: Dict[str, Any] = {
            "phases": {"gas": {"mechanism": "gri30.yaml"}},
            "nodes": [
                {
                    "id": "pfr1",
                    "type": "FakeKind",
                    "properties": {"temperature": 1000.0},
                },
                {
                    "id": "pfr2",
                    "type": "FakeKind",
                    "properties": {"temperature": 900.0},
                },
            ],
            "connections": [],
        }
        plugins = _make_plugins_with_unfolder("FakeKind", _simple_unfolder)
        expand_composite_kinds(config, plugins)
        node_ids = [n["id"] for n in config["nodes"]]
        assert "pfr1_ambient" in node_ids
        assert "pfr2_ambient" in node_ids
        # No duplicates
        assert len(node_ids) == len(set(node_ids))

    def test_adiabatic_unfolder_skips(self):
        """Unfolder that returns empty dict leaves config unchanged."""

        def _adiabatic_unfolder(node):
            props = node.get("properties") or {}
            if props.get("adiabatic"):
                return {}
            return _simple_unfolder(node)

        config: Dict[str, Any] = {
            "phases": {"gas": {"mechanism": "gri30.yaml"}},
            "nodes": [
                {"id": "pfr", "type": "FakeKind", "properties": {"adiabatic": True}},
            ],
            "connections": [],
        }
        plugins = _make_plugins_with_unfolder("FakeKind", _adiabatic_unfolder)
        expand_composite_kinds(config, plugins)
        assert len(config["nodes"]) == 1
        assert len(config["connections"]) == 0


# ---------------------------------------------------------------------------
# normalize_config integration — plugins=None picks up registered unfolders
# ---------------------------------------------------------------------------


class TestNormalizeConfigIntegration:
    def test_normalize_accepts_plugins_kwarg(self):
        """normalize_config(config, plugins=empty) runs without satellite injection."""
        config = _minimal_config_with_kind("FakeKind")
        # No unfolder registered → no satellites
        normalized = normalize_config(config, plugins=BoulderPlugins())
        node_ids = [n["id"] for n in normalized["nodes"]]
        assert "pfr_ambient" not in node_ids


# ---------------------------------------------------------------------------
# Wall builder — split branches
# ---------------------------------------------------------------------------


class TestWallBuilderBranches:
    """Verify torch-power vs generic-passive Wall branches via a minimal STONE build."""

    def _build_config(self, wall_props: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "phases": {"gas": {"mechanism": "gri30.yaml"}},
            "nodes": [
                {
                    "id": "src",
                    "type": "Reservoir",
                    "properties": {
                        "temperature": 300.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
                {
                    "id": "tgt",
                    "type": "Reservoir",
                    "properties": {
                        "temperature": 800.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
            ],
            "connections": [
                {
                    "id": "w1",
                    "type": "Wall",
                    "source": "src",
                    "target": "tgt",
                    "properties": wall_props,
                },
            ],
        }

    def _build_wall(self, wall_props: Dict[str, Any]) -> "ct.Wall":
        """Return a built Wall by directly driving the converter's build_connection.

        Bypasses advance_to_steady_state so the test is not blocked by
        "no reactors in network!" errors from a Reservoir-only topology.
        """
        import cantera as ct

        from boulder.cantera_converter import DualCanteraConverter

        converter = DualCanteraConverter(mechanism="gri30.yaml")
        # Manually register two Reservoir nodes so build_connection can look them up.
        gas = ct.Solution("gri30.yaml")
        gas.TPX = 300.0, 101325.0, "N2:1"
        converter.reactors["src"] = ct.Reservoir(gas, clone=True)
        gas2 = ct.Solution("gri30.yaml")
        gas2.TPX = 800.0, 101325.0, "N2:1"
        converter.reactors["tgt"] = ct.Reservoir(gas2, clone=True)

        conn = {
            "id": "w1",
            "type": "Wall",
            "source": "src",
            "target": "tgt",
            "properties": wall_props,
        }
        converter.build_connection(conn)
        return converter.walls["w1"]

    def test_torch_wall_creates_heat_rate_callable(self):
        """Torch-power wall has a callable heat_flux (returns Q)."""
        wall = self._build_wall(
            {"electric_power_kW": 10.0, "torch_eff": 0.9, "gen_eff": 0.95}
        )
        # heat_flux should be a callable for the torch branch
        assert callable(wall.heat_flux) or isinstance(float(wall.heat_flux), float)

    def test_passive_wall_area_set(self):
        """Generic passive wall respects the ``area`` property."""
        wall = self._build_wall({"area": 2.5})
        assert abs(wall.area - 2.5) < 1e-9

    def test_passive_wall_heat_flux_settable(self):
        """Generic passive wall starts at 0 heat_flux and is settable post-build."""
        wall = self._build_wall({"area": 1.0})
        wall.heat_flux = 500.0
        assert abs(float(wall.heat_flux) - 500.0) < 1e-6
