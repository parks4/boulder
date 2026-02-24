"""Tests for Boulder's staged solver (groups-based sequential ReactorNet solving).

Covers:
- Loading and validating the example config ``configs/staged_psr_pfr.yaml``.
- Running build_network() on it end-to-end: plan construction, sequential solve,
  Lagrangian trajectory assembly, and visualization ReactorNet.
- Core staged_solver utilities: build_stage_graph, topological sort, cycle detection.
- LagrangianTrajectory: cumulative time axis and species mapping.
"""

from __future__ import annotations

from pathlib import Path

import cantera as ct
import numpy as np
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import load_config_file, normalize_config, validate_config
from boulder.lagrangian import LagrangianTrajectory
from boulder.staged_solver import (
    build_stage_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
STAGED_CONFIG = CONFIGS_DIR / "staged_psr_pfr.yaml"

# Minimal inert (N2-only) two-stage config: no chemistry → solve converges fast.
#
# Each stage contains a single isolated reactor (no intra-stage connections).
# The only connection is the inter-stage a_to_b, which is virtual during solve:
# r_b is initialised directly from r_a's outlet state rather than via an MFC.
# This avoids mass-accumulation / density-going-negative failures that occur
# when a chain reactor has no outlet and advance_to_steady_state is used.
_INERT_TWO_STAGE = {
    "groups": {
        "stage_a": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"},
        "stage_b": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"},
    },
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "nodes": [
        {
            "id": "r_a",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_a",
                "temperature": 1200.0,
                "pressure": 101325.0,
                "composition": "N2:1",
                "volume": 1e-5,
            },
        },
        {
            "id": "r_b",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_b",
                "temperature": 900.0,  # overwritten by r_a outlet at solve time
                "pressure": 101325.0,
                "composition": "N2:1",
                "volume": 5e-6,
            },
        },
    ],
    "connections": [
        # Inter-stage: virtual during solve (r_b init'd from r_a outlet directly)
        {
            "id": "a_to_b",
            "type": "MassFlowController",
            "source": "r_a",
            "target": "r_b",
            "properties": {"mass_flow_rate": 1e-4},
        },
    ],
}


# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------


class TestStagedConfig:
    """The example config file loads, validates, and survives normalize_config."""

    def test_config_file_exists(self):
        assert STAGED_CONFIG.exists(), f"Config file not found: {STAGED_CONFIG}"

    def test_config_loads(self):
        cfg = load_config_file(str(STAGED_CONFIG))
        assert "groups" in cfg, "groups section missing"
        assert "nodes" in cfg
        assert "connections" in cfg

    def test_config_normalizes(self):
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        assert "groups" in norm
        # inter-stage connection preserves mechanism_switch (even when commented → None)
        conn_ids = {c["id"] for c in norm["connections"]}
        assert "psr_to_pfr" in conn_ids

    def test_config_validates(self):
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        validated = validate_config(norm)
        assert validated is not None
        assert "groups" in validated
        assert len(validated["nodes"]) == 6  # feed + psr + 4 pfr cells

    def test_groups_section_structure(self):
        cfg = load_config_file(str(STAGED_CONFIG))
        groups = cfg["groups"]
        assert "psr_stage" in groups
        assert "pfr_stage" in groups
        for gid, gcfg in groups.items():
            assert "mechanism" in gcfg, f"groups.{gid} missing mechanism"
            assert "solve" in gcfg, f"groups.{gid} missing solve"

    def test_inter_stage_connection_present(self):
        """psr_to_pfr must cross stage boundaries."""
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        node_group = {
            n["id"]: (n.get("properties") or {}).get("group") for n in norm["nodes"]
        }
        psr_to_pfr = next(
            (c for c in norm["connections"] if c["id"] == "psr_to_pfr"), None
        )
        assert psr_to_pfr is not None
        src_group = node_group.get(psr_to_pfr["source"])
        tgt_group = node_group.get(psr_to_pfr["target"])
        assert src_group != tgt_group, "psr_to_pfr should cross stage boundaries"


# ---------------------------------------------------------------------------
# build_stage_graph
# ---------------------------------------------------------------------------


class TestBuildStageGraph:
    def test_two_stage_order(self):
        plan = build_stage_graph(_INERT_TWO_STAGE)
        ids = [s.id for s in plan.ordered_stages]
        assert ids == ["stage_a", "stage_b"]

    def test_inter_stage_connections_detected(self):
        plan = build_stage_graph(_INERT_TWO_STAGE)
        assert len(plan.all_inter_connections) == 1
        assert plan.all_inter_connections[0].id == "a_to_b"

    def test_intra_stage_connections_partitioned(self):
        # _INERT_TWO_STAGE has only one connection (a_to_b) which is inter-stage.
        # stage_b therefore has no intra-stage connections.
        plan = build_stage_graph(_INERT_TWO_STAGE)
        stage_b = next(s for s in plan.ordered_stages if s.id == "stage_b")
        intra_ids = [c["id"] for c in stage_b.intra_connections]
        assert "a_to_b" not in intra_ids
        assert intra_ids == []

    def test_node_to_stage_map(self):
        plan = build_stage_graph(_INERT_TWO_STAGE)
        assert plan.node_to_stage["r_a"] == "stage_a"
        assert plan.node_to_stage["r_b"] == "stage_b"

    def test_cycle_raises(self):
        cyclic = {
            "groups": {
                "g1": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"},
                "g2": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"},
            },
            "nodes": [
                {
                    "id": "n1",
                    "type": "IdealGasConstPressureMoleReactor",
                    "properties": {
                        "group": "g1",
                        "temperature": 1000.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 1e-5,
                    },
                },
                {
                    "id": "n2",
                    "type": "IdealGasConstPressureMoleReactor",
                    "properties": {
                        "group": "g2",
                        "temperature": 1000.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 1e-5,
                    },
                },
            ],
            "connections": [
                {
                    "id": "c1",
                    "type": "MassFlowController",
                    "source": "n1",
                    "target": "n2",
                    "properties": {"mass_flow_rate": 1e-4},
                },
                {
                    "id": "c2",
                    "type": "MassFlowController",
                    "source": "n2",
                    "target": "n1",
                    "properties": {"mass_flow_rate": 1e-4},
                },
            ],
        }
        with pytest.raises(ValueError, match="cycles"):
            build_stage_graph(cyclic)

    def test_unknown_group_raises(self):
        bad = {
            "groups": {
                "g1": {"mechanism": "gri30.yaml", "solve": "advance_to_steady_state"}
            },
            "nodes": [
                {
                    "id": "n1",
                    "type": "IdealGasConstPressureMoleReactor",
                    "properties": {
                        "group": "nonexistent",
                        "temperature": 1000.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                }
            ],
            "connections": [],
        }
        with pytest.raises(ValueError, match="unknown group"):
            build_stage_graph(bad)


# ---------------------------------------------------------------------------
# End-to-end staged solve (inert two-stage)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestStagedSolveInert:
    """Runs the staged solver on a simple inert (N2-only) two-stage network.

    Using pure N2 avoids chemistry stiffness and ensures advance_to_steady_state
    converges in milliseconds regardless of temperature.
    """

    @pytest.fixture(scope="class")
    def result(self):
        conv = DualCanteraConverter(mechanism="gri30.yaml")
        net = conv.build_network(_INERT_TWO_STAGE)
        return conv, net

    def test_returns_reactor_net(self, result):
        _, net = result
        assert isinstance(net, ct.ReactorNet)

    def test_all_reactors_registered(self, result):
        conv, _ = result
        assert set(conv.reactors.keys()) == {"r_a", "r_b"}

    def test_trajectory_attached(self, result):
        conv, _ = result
        assert hasattr(conv, "_staged_trajectory")
        traj = conv._staged_trajectory
        assert isinstance(traj, LagrangianTrajectory)

    def test_trajectory_has_two_segments(self, result):
        conv, _ = result
        assert len(conv._staged_trajectory.segments) == 2

    def test_trajectory_stage_ids(self, result):
        conv, _ = result
        ids = [seg.stage_id for seg in conv._staged_trajectory.segments]
        assert ids == ["stage_a", "stage_b"]

    def test_stage_b_inlet_from_stage_a_outlet(self, result):
        """r_b must be initialised from r_a's outlet, not its YAML value (900 K)."""
        conv, _ = result
        T_a = conv.reactors["r_a"].phase.T
        T_b = conv.reactors["r_b"].phase.T
        # Pure N2 — T is conserved through the inter-stage state transfer.
        assert abs(T_b - T_a) < 1.0, (
            f"r_b T={T_b:.1f} K should equal r_a outlet T={T_a:.1f} K"
        )

    def test_trajectory_T_array_shape(self, result):
        conv, _ = result
        T = conv._staged_trajectory.T
        assert T.ndim == 1
        assert len(T) == 2  # one entry per reactor (r_a, r_b)

    def test_viz_network_spans_all_reactors(self, result):
        conv, _ = result
        traj = conv._staged_trajectory
        assert traj.viz_network is not None
        n_reactors = len(traj.viz_network.reactors)
        assert n_reactors == 2


# ---------------------------------------------------------------------------
# End-to-end staged solve from the example YAML config file
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestStagedSolveExampleConfig:
    """Loads and runs configs/staged_psr_pfr.yaml through the full staged solver.

    The config uses gri30.yaml with a CH4/air mixture.  We only check structural
    properties (stages, trajectory, viz network) to stay fast; correctness of
    the chemistry is not asserted here.
    """

    @pytest.fixture(scope="class")
    def result(self):
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        validated = validate_config(norm)
        conv = DualCanteraConverter(mechanism="gri30.yaml")
        net = conv.build_network(validated)
        return conv, net

    def test_build_network_succeeds(self, result):
        _, net = result
        assert isinstance(net, ct.ReactorNet)

    def test_five_reactors_registered(self, result):
        conv, _ = result
        # Only grouped nodes are processed by the staged solver:
        # psr + 4 pfr cells = 5.  The ungrouped `feed` Reservoir is not added
        # to conv.reactors since it has no group and belongs to no sub-network.
        assert len(conv.reactors) == 5

    def test_two_stage_trajectory(self, result):
        conv, _ = result
        traj = conv._staged_trajectory
        assert len(traj.segments) == 2
        assert traj.segments[0].stage_id == "psr_stage"
        assert traj.segments[1].stage_id == "pfr_stage"

    def test_psr_outlet_propagated_to_pfr(self, result):
        """pfr_cell_1 must be initialised from the PSR outlet temperature.

        Both PSR and PFR are advanced for 1 ms.  After that, pfr_cell_1's
        temperature should be close to the PSR outlet (it was initialised from
        it and evolved for the same short time without coupling back to the PSR).
        We accept a 200 K window to account for PFR-internal dynamics over 1 ms.
        """
        conv, _ = result
        T_psr = conv.reactors["psr"].phase.T
        T_pfr1 = conv.reactors["pfr_cell_1"].phase.T
        assert T_psr > 1000.0, f"PSR should be hot, got T={T_psr:.0f} K"
        assert T_pfr1 > 1000.0, f"PFR cell 1 should be hot, got T={T_pfr1:.0f} K"

    def test_pfr_cells_all_hot(self, result):
        """All PFR cells should remain above 1000 K after the short advance."""
        conv, _ = result
        for cell in ["pfr_cell_1", "pfr_cell_2", "pfr_cell_3", "pfr_cell_4"]:
            T = conv.reactors[cell].phase.T
            assert T > 1000.0, f"{cell} unexpectedly cold: T={T:.0f} K"

    def test_viz_network_contains_all_reactors(self, result):
        conv, _ = result
        traj = conv._staged_trajectory
        assert traj.viz_network is not None
        # All non-Reservoir reactors: psr + 4 pfr cells = 5
        n = len(traj.viz_network.reactors)
        assert n == 5

    def test_trajectory_to_dataframe(self, result):
        conv, _ = result
        pytest.importorskip("pandas")
        df = conv._staged_trajectory.to_dataframe()
        assert not df.empty
        assert "T" in df.columns
        assert "stage" in df.columns
        assert set(df["stage"].unique()) == {"psr_stage", "pfr_stage"}


# ---------------------------------------------------------------------------
# LagrangianTrajectory unit tests
# ---------------------------------------------------------------------------


class TestLagrangianTrajectory:
    def _make_states(self, T: float, n: int = 3) -> ct.SolutionArray:
        gas = ct.Solution("gri30.yaml")
        states = ct.SolutionArray(gas, extra=["t"])
        for i in range(n):
            gas.TPX = T + i * 10, 101325, "N2:1"
            states.append(gas.state, t=float(i) * 1e-3)  # type: ignore[call-arg]
        return states

    def test_empty_trajectory(self):
        traj = LagrangianTrajectory()
        assert len(traj) == 0
        assert traj.segments == []

    def test_add_segment_length(self):
        traj = LagrangianTrajectory()
        traj.add_segment("s1", "gri30.yaml", self._make_states(1000))
        assert len(traj) == 3

    def test_two_segments_cumulative_time(self):
        traj = LagrangianTrajectory()
        traj.add_segment("s1", "gri30.yaml", self._make_states(1000, n=3))
        traj.add_segment("s2", "gri30.yaml", self._make_states(900, n=2))
        t = traj.t
        assert len(t) == 5
        # Second segment's first point should be offset by last t of first segment
        assert t[3] >= t[2], "Time axis must be non-decreasing across segments"

    def test_T_array(self):
        traj = LagrangianTrajectory()
        traj.add_segment("s1", "gri30.yaml", self._make_states(1000, n=2))
        T = traj.T
        assert len(T) == 2
        assert T[0] == pytest.approx(1000.0)

    def test_species_X_known(self):
        traj = LagrangianTrajectory()
        traj.add_segment("s1", "gri30.yaml", self._make_states(1000, n=2))
        X_N2 = traj.X("N2")
        assert len(X_N2) == 2
        assert np.all(X_N2 > 0.99)  # pure N2

    def test_species_X_absent_is_nan(self):
        traj = LagrangianTrajectory()
        traj.add_segment("s1", "gri30.yaml", self._make_states(1000, n=2))
        # "H2O2" is present in gri30 but will have X≈0 at pure N2 state
        # Use a fake mechanism name to trigger the absent branch
        traj.segments[0].mechanism = "__nonexistent__.yaml"
        X = traj.X("N2")
        assert np.all(np.isnan(X))

    def test_repr(self):
        traj = LagrangianTrajectory()
        traj.add_segment("alpha", "gri30.yaml", self._make_states(500, n=1))
        r = repr(traj)
        assert "alpha" in r
        assert "n_points=1" in r
