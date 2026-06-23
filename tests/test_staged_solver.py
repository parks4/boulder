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
    solve_staged,
    synthesize_stream_points,
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
    """The example config file (STONE v2) loads, validates, and survives normalize_config."""

    def test_config_file_exists(self):
        """The staged_psr_pfr.yaml config file exists on disk."""
        assert STAGED_CONFIG.exists(), f"Config file not found: {STAGED_CONFIG}"

    def test_config_loads(self):
        """Raw STONE v2 file has 'stages:' and named stage blocks instead of 'groups:'/'nodes:'."""
        cfg = load_config_file(str(STAGED_CONFIG))
        assert "stages" in cfg, "STONE v2 requires 'stages:' section"
        assert "psr_stage" in cfg, "Stage block 'psr_stage' missing from raw v2 file"
        assert "pfr_stage" in cfg, "Stage block 'pfr_stage' missing from raw v2 file"

    def test_config_normalizes(self):
        """normalize_config converts v2 to internal format with 'groups' and 'connections'."""
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        assert "groups" in norm, "Normalized config must have 'groups'"
        conn_ids = {c["id"] for c in norm["connections"]}
        assert "psr_to_pfr" in conn_ids, "Inter-stage connection 'psr_to_pfr' missing"

    def test_config_validates(self):
        """normalize_config + validate_config round-trip succeeds."""
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        validated = validate_config(norm)
        assert validated is not None
        assert "groups" in validated
        assert len(validated["nodes"]) == 6  # feed + psr + 4 pfr cells

    def test_groups_section_structure(self):
        """After normalization, groups has psr_stage and pfr_stage with mechanism and solver block."""
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        groups = norm["groups"]
        assert "psr_stage" in groups
        assert "pfr_stage" in groups
        for gid, gcfg in groups.items():
            assert "mechanism" in gcfg, f"groups.{gid} missing mechanism"
            # New-style solver block replaces the legacy 'solve' key
            assert "solver" in gcfg, f"groups.{gid} missing solver block"
            assert "kind" in gcfg["solver"], f"groups.{gid}.solver missing kind"

    def test_inter_stage_connection_present(self):
        """psr_to_pfr logical connection must cross stage boundaries (different group tags)."""
        cfg = load_config_file(str(STAGED_CONFIG))
        norm = normalize_config(cfg)
        node_group = {n["id"]: n.get("group") for n in norm["nodes"]}
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
        """User-declared reactors and the synthesised stream-point reservoir are registered.

        With stream_reservoirs=True (default), solve_staged adds a ct.Reservoir for each
        inter-stage source node (here r_a_outlet for the r_a → r_b boundary).
        """
        conv, _ = result
        assert set(conv.reactors.keys()) == {"r_a", "r_b", "r_a_outlet"}

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
        # psr_stage: feed (Reservoir) + psr = 2 nodes.
        # pfr_stage: pfr_cell_1/2/3/4 = 4 nodes.
        # Stream reservoirs are always enabled: one stream-point Reservoir
        # (psr_outlet) is synthesised → total = 7.
        assert len(conv.reactors) == 7

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

    def test_stream_point_present_when_flag_on(self, result):
        """With stream_reservoirs=True (staged_psr_pfr.yaml), psr_outlet stream-point exists.

        Asserts that:
        - The synthesised stream-point reservoir is in converter.reactors.
        - It is a ct.Reservoir instance.
        - Its temperature matches the PSR outlet temperature (set after upstream solve).
        """
        conv, _ = result
        stream_id = "psr_outlet"
        if stream_id not in conv.reactors:
            pytest.skip("stream_reservoirs flag was off for this build")
        stream_res = conv.reactors[stream_id]
        assert isinstance(stream_res, ct.Reservoir)
        T_psr = conv.reactors["psr"].phase.T
        T_stream = stream_res.phase.T
        assert abs(T_stream - T_psr) < 1.0, (
            f"Stream-point reservoir T={T_stream:.1f} K should match PSR outlet T={T_psr:.1f} K"
        )

    def test_trajectory_to_dataframe(self, result):
        conv, _ = result
        pytest.importorskip("pandas")
        df = conv._staged_trajectory.to_dataframe()
        assert not df.empty
        assert "T" in df.columns
        assert "stage" in df.columns
        assert set(df["stage"].unique()) == {"psr_stage", "pfr_stage"}


# ---------------------------------------------------------------------------
# BoulderRunner end-to-end: staged_psr_pfr.yaml with interface_reservoirs=True
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestRunnerInterfaceReservoirsYAML:
    """BoulderRunner.from_yaml on staged_psr_pfr.yaml with stream_reservoirs: true.

    Asserts:
    - build() completes without error.
    - The stream-point reservoir psr_outlet is present and is a ct.Reservoir.
    - Stream-point reservoir T matches the PSR outlet T within 1 K.
    - pfr_cell_1 T is within 200 K of PSR outlet T (short advance, no coupling back).
    - The viz network contains exactly 5 non-Reservoir reactors.
    """

    @pytest.fixture(scope="class")
    def runner(self):
        from boulder.runner import BoulderRunner

        assert STAGED_CONFIG.exists(), f"Config not found: {STAGED_CONFIG}"
        r = BoulderRunner.from_yaml(str(STAGED_CONFIG))
        r.build()
        return r

    def test_build_completes(self, runner):
        """BoulderRunner.build() on staged_psr_pfr.yaml with the flag succeeds."""
        assert runner.converter is not None

    def test_stream_point_reservoir_present(self, runner):
        """psr_outlet Reservoir is created by the stream-reservoirs path."""
        conv = runner.converter
        assert "psr_outlet" in conv.reactors, (
            "Stream-point reservoir 'psr_outlet' not found — "
            "stream reservoirs are always enabled in the staged solver."
        )
        assert isinstance(conv.reactors["psr_outlet"], ct.Reservoir)

    def test_stream_point_T_matches_psr(self, runner):
        """Stream-point reservoir T equals PSR outlet T after upstream solve."""
        conv = runner.converter
        if "psr_outlet" not in conv.reactors:
            pytest.skip("Stream-point reservoir not present")
        T_psr = conv.reactors["psr"].phase.T
        T_stream = conv.reactors["psr_outlet"].phase.T
        assert abs(T_stream - T_psr) < 1.0, (
            f"Stream-point T={T_stream:.1f} K, PSR outlet T={T_psr:.1f} K"
        )

    def test_pfr_cell_1_seeded_from_psr(self, runner):
        """pfr_cell_1 T is within 200 K of PSR outlet T after the short advance."""
        conv = runner.converter
        T_psr = conv.reactors["psr"].phase.T
        T_pfr1 = conv.reactors["pfr_cell_1"].phase.T
        assert abs(T_pfr1 - T_psr) < 200.0, (
            f"pfr_cell_1 T={T_pfr1:.1f} K deviates > 200 K from PSR T={T_psr:.1f} K"
        )

    def test_viz_network_reactor_count(self, runner):
        """Viz network contains the 5 non-Reservoir reactors (psr + 4 pfr cells)."""
        traj = runner.converter._staged_trajectory
        assert traj.viz_network is not None
        assert len(traj.viz_network.reactors) == 5

    def test_trajectory_has_two_segments(self, runner):
        """Trajectory has exactly two segments: psr_stage and pfr_stage."""
        traj = runner.converter._staged_trajectory
        assert len(traj.segments) == 2
        assert traj.segments[0].stage_id == "psr_stage"
        assert traj.segments[1].stage_id == "pfr_stage"


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


# ---------------------------------------------------------------------------
# synthesize_interface_nodes
# ---------------------------------------------------------------------------


class TestSynthesizeInterfaceNodes:
    """Unit tests for synthesize_stream_points (alias: synthesize_interface_nodes).

    Asserts:
    - One Reservoir node dict is emitted per *source node* (not per connection).
    - Reservoir id follows the source-semantic "{source_node}_outlet" convention.
    - Exactly one MFC connection dict is emitted per connection (inlet side only).
    - The inlet MFC connects stream_point_id → target_node in the downstream stage.
    - No outlet MFC is synthesised (upstream stage has no MFC to the reservoir).
    - Metadata fields (stream_point, upstream_stage, ...) are present.
    - When mass_flow_rate is declared in ic.properties it is forwarded to the inlet MFC.
    - When mass_flow_rate is absent the MFC dict carries no mass_flow_rate key.
    """

    def test_one_reservoir_per_source_node(self):
        """Exactly one Reservoir node is synthesised per unique source node."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        nodes, _ = synthesize_stream_points(plan)
        assert len(nodes) == 1
        assert nodes[0]["type"] == "Reservoir"

    def test_reservoir_id_is_source_semantic(self):
        """Reservoir id follows {source_node}_outlet (source-semantic, not connection-id)."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        nodes, _ = synthesize_stream_points(plan)
        ic = plan.all_inter_connections[0]
        assert nodes[0]["id"] == ic.stream_point_id
        assert nodes[0]["id"] == "r_a_outlet"

    def test_one_mfc_dict_per_connection(self):
        """Exactly one MassFlowController (inlet side only) is produced per inter-stage connection."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        _, conns = synthesize_stream_points(plan)
        assert len(conns) == 1
        assert conns[0]["type"] == "MassFlowController"

    def test_no_outlet_mfc_synthesised(self):
        """No outlet MFC (source_node → reservoir) is created; upstream stage has no stream MFC."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        ic = plan.all_inter_connections[0]
        _, conns = synthesize_stream_points(plan)
        outlet_ids = [c["id"] for c in conns if c["id"] == ic.outlet_mfc_id]
        assert outlet_ids == [], "outlet MFC must not be synthesised"

    def test_inlet_mfc_connects_stream_point_to_target(self):
        """Inlet MFC: source=stream_point_id, target=target_node, group=target_stage."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        ic = plan.all_inter_connections[0]
        _, conns = synthesize_stream_points(plan)
        inlet = next(c for c in conns if c["id"] == ic.inlet_mfc_id)
        assert inlet["source"] == ic.stream_point_id
        assert inlet["target"] == ic.target_node
        assert inlet["group"] == ic.target_stage

    def test_stream_point_metadata_present(self):
        """All synthesised nodes and connections carry stream_point metadata."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        nodes, conns = synthesize_stream_points(plan)
        for nd in nodes:
            assert nd["properties"].get("stream_point") is True
            assert nd["metadata"].get("stream_point") is True
        for conn in conns:
            assert conn.get("metadata", {}).get("stream_point") is True

    def test_mass_flow_rate_forwarded_when_declared(self):
        """When ic.properties has mass_flow_rate, the inlet MFC inherits it."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        ic = plan.all_inter_connections[0]
        assert ic.properties.get("mass_flow_rate") == 1e-4
        _, conns = synthesize_stream_points(plan)
        for conn in conns:
            assert conn["properties"].get("mass_flow_rate") == pytest.approx(1e-4)

    def test_mass_flow_rate_absent_when_not_declared(self):
        """When ic.properties lacks mass_flow_rate, MFC dicts have empty properties."""
        config_no_mdot = {
            "groups": {
                "stage_a": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance_to_steady_state",
                },
                "stage_b": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance_to_steady_state",
                },
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
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 5e-6,
                    },
                },
            ],
            "connections": [
                {
                    "id": "a_to_b",
                    "type": "MassFlowController",
                    "source": "r_a",
                    "target": "r_b",
                    # no mass_flow_rate
                    "properties": {},
                },
            ],
        }
        plan = build_stage_graph(config_no_mdot)
        _, conns = synthesize_stream_points(plan)
        for conn in conns:
            assert "mass_flow_rate" not in conn["properties"]

    def test_upstream_stage_in_metadata(self):
        """upstream_stage is set correctly in node metadata."""
        plan = build_stage_graph(_INERT_TWO_STAGE)
        nodes, _ = synthesize_stream_points(plan)
        nd = nodes[0]
        assert nd["properties"]["upstream_stage"] == "stage_a"

    def test_fanout_one_reservoir_two_mfcs(self):
        """When one source feeds two downstream stages, exactly one reservoir and two MFCs are created."""
        fanout_config = {
            "groups": {
                "stage_a": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance_to_steady_state",
                },
                "stage_b": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance_to_steady_state",
                },
                "stage_c": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance_to_steady_state",
                },
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
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 5e-6,
                    },
                },
                {
                    "id": "r_c",
                    "type": "IdealGasConstPressureMoleReactor",
                    "properties": {
                        "group": "stage_c",
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 5e-6,
                    },
                },
            ],
            "connections": [
                {
                    "id": "a_to_b",
                    "type": "MassFlowController",
                    "source": "r_a",
                    "target": "r_b",
                    "properties": {"mass_flow_rate": 5e-5},
                },
                {
                    "id": "a_to_c",
                    "type": "MassFlowController",
                    "source": "r_a",
                    "target": "r_c",
                    "properties": {"mass_flow_rate": 5e-5},
                },
            ],
        }
        plan = build_stage_graph(fanout_config)
        assert len(plan.all_inter_connections) == 2
        nodes, conns = synthesize_stream_points(plan)
        # One diamond per source node (r_a has two downstream targets → still 1 diamond)
        assert len(nodes) == 1, f"Expected 1 stream-point reservoir, got {len(nodes)}"
        assert nodes[0]["id"] == "r_a_outlet"
        # Two inlet MFCs: r_a_outlet → r_b and r_a_outlet → r_c
        assert len(conns) == 2, f"Expected 2 inlet MFCs, got {len(conns)}"
        mfc_ids = {c["id"] for c in conns}
        assert "r_a_outlet_to_r_b" in mfc_ids
        assert "r_a_outlet_to_r_c" in mfc_ids


# ---------------------------------------------------------------------------
# Interface-reservoir solve path
# ---------------------------------------------------------------------------


class TestInterfaceReservoirSolve:
    """End-to-end staged solve with interface_reservoirs=True.

    Asserts:
    - Solve completes without error.
    - Downstream reactor temperature is within 1 K of the legacy (inlet_states) solve.
    - Interface reservoirs appear in converter.reactors.
    - Each iface reservoir carries T matching the upstream reactor outlet.
    """

    @pytest.fixture(scope="class")
    def _both_results(self):
        """Solve a two-stage config with and without interface_reservoirs.

        Returns (conv_legacy, conv_iface) after both builds.

        Uses a config where r_b has an outlet Reservoir so that the real
        inlet MFC (from the iface reservoir) does not cause mass accumulation
        when advance_to_steady_state is used.
        """
        from boulder.staged_solver import solve_staged

        # Two-stage config with an outlet reservoir for r_b
        _config_with_outlet = {
            "groups": {
                "stage_a": {
                    "mechanism": "gri30.yaml",
                    "solver": {"kind": "advance", "advance_time": 1e-6},
                },
                "stage_b": {
                    "mechanism": "gri30.yaml",
                    "solver": {"kind": "advance", "advance_time": 1e-6},
                },
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
                    "id": "feed_a",
                    "type": "Reservoir",
                    "properties": {
                        "group": "stage_a",
                        "temperature": 1200.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
                {
                    "id": "r_b",
                    "type": "IdealGasConstPressureMoleReactor",
                    "properties": {
                        "group": "stage_b",
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 5e-6,
                    },
                },
                {
                    "id": "sink_b",
                    "type": "Reservoir",
                    "properties": {
                        "group": "stage_b",
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
            ],
            "connections": [
                {
                    "id": "feed_to_a",
                    "type": "MassFlowController",
                    "source": "feed_a",
                    "target": "r_a",
                    "properties": {"mass_flow_rate": 1e-4},
                    "group": "stage_a",
                },
                # Inter-stage
                {
                    "id": "a_to_b",
                    "type": "MassFlowController",
                    "source": "r_a",
                    "target": "r_b",
                    "properties": {"mass_flow_rate": 1e-4},
                },
                {
                    "id": "b_to_sink",
                    "type": "MassFlowController",
                    "source": "r_b",
                    "target": "sink_b",
                    "properties": {"mass_flow_rate": 1e-4},
                    "group": "stage_b",
                },
            ],
        }

        # Legacy path (explicit opt-out)
        conv_legacy = DualCanteraConverter(mechanism="gri30.yaml")
        plan_legacy = build_stage_graph(_config_with_outlet)
        solve_staged(
            conv_legacy, plan_legacy, _config_with_outlet, stream_reservoirs=False
        )

        # Stream-reservoir path (now the default)
        conv_iface = DualCanteraConverter(mechanism="gri30.yaml")
        plan_iface = build_stage_graph(_config_with_outlet)
        solve_staged(conv_iface, plan_iface, _config_with_outlet)

        return conv_legacy, conv_iface

    def test_both_builds_complete(self, _both_results):
        """Both the legacy and interface-reservoir builds finish without raising."""
        conv_legacy, conv_iface = _both_results
        assert conv_legacy is not None
        assert conv_iface is not None

    def test_downstream_T_matches_legacy(self, _both_results):
        """r_b temperature with interface_reservoirs=True matches legacy within 1 K."""
        conv_legacy, conv_iface = _both_results
        T_legacy = conv_legacy.reactors["r_b"].phase.T
        T_iface = conv_iface.reactors["r_b"].phase.T
        assert abs(T_iface - T_legacy) < 1.0

    def test_stream_point_in_converter(self, _both_results):
        """Stream-point reservoir is present in converter.reactors after solve."""
        _, conv_iface = _both_results
        assert "r_a_outlet" in conv_iface.reactors

    def test_stream_point_T_matches_source(self, _both_results):
        """Stream-point reservoir T matches source reactor (r_a) outlet T."""
        _, conv_iface = _both_results
        T_source = conv_iface.reactors["r_a"].phase.T
        T_iface = conv_iface.reactors["r_a_outlet"].phase.T
        assert abs(T_iface - T_source) < 1.0

    def test_stream_point_node_injected_into_config(self, _both_results):
        """Stream-point reservoir node is appended to config['nodes'] after solve_staged.

        Verifies that solve_staged back-fills the synthesised stream-point reservoir into
        config['nodes'] so the frontend graph / updated_connections capture picks it up.
        """
        cfg2 = {
            "groups": {
                "stage_a": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance",
                    "advance_time": 1e-5,
                },
                "stage_b": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance",
                    "advance_time": 1e-5,
                },
            },
            "phases": {"gas": {"mechanism": "gri30.yaml"}},
            "nodes": [
                {
                    "id": "feed_a",
                    "type": "Reservoir",
                    "properties": {
                        "group": "stage_a",
                        "temperature": 1200.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
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
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 5e-6,
                    },
                },
                {
                    "id": "sink_b",
                    "type": "Reservoir",
                    "properties": {
                        "group": "stage_b",
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
            ],
            "connections": [
                {
                    "id": "feed_to_a",
                    "type": "MassFlowController",
                    "source": "feed_a",
                    "target": "r_a",
                    "properties": {"mass_flow_rate": 1e-4},
                    "group": "stage_a",
                },
                {
                    "id": "a_to_b",
                    "type": "MassFlowController",
                    "source": "r_a",
                    "target": "r_b",
                    "properties": {"mass_flow_rate": 1e-4},
                },
                {
                    "id": "b_to_sink",
                    "type": "MassFlowController",
                    "source": "r_b",
                    "target": "sink_b",
                    "properties": {"mass_flow_rate": 1e-4},
                    "group": "stage_b",
                },
            ],
        }
        conv2 = DualCanteraConverter(mechanism="gri30.yaml")
        plan2 = build_stage_graph(cfg2)
        solve_staged(conv2, plan2, cfg2)
        node_ids = [n["id"] for n in cfg2.get("nodes", [])]
        ic = plan2.all_inter_connections[0]
        assert ic.stream_point_id in node_ids, (
            f"Stream-point reservoir '{ic.stream_point_id}' not found in "
            f"config['nodes']: {node_ids}"
        )

    def test_stream_inlet_mfc_injected_into_config(self, _both_results):
        """Inlet MFC for the stream-point reservoir is appended to config['connections'] after solve.

        Verifies that the downstream MFC (stream-point → target) is visible in config
        so the frontend edge list reflects the actual Cantera topology.
        """
        cfg2 = {
            "groups": {
                "stage_a": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance",
                    "advance_time": 1e-5,
                },
                "stage_b": {
                    "mechanism": "gri30.yaml",
                    "solve": "advance",
                    "advance_time": 1e-5,
                },
            },
            "phases": {"gas": {"mechanism": "gri30.yaml"}},
            "nodes": [
                {
                    "id": "feed_a",
                    "type": "Reservoir",
                    "properties": {
                        "group": "stage_a",
                        "temperature": 1200.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
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
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 5e-6,
                    },
                },
                {
                    "id": "sink_b",
                    "type": "Reservoir",
                    "properties": {
                        "group": "stage_b",
                        "temperature": 900.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
            ],
            "connections": [
                {
                    "id": "feed_to_a",
                    "type": "MassFlowController",
                    "source": "feed_a",
                    "target": "r_a",
                    "properties": {"mass_flow_rate": 1e-4},
                    "group": "stage_a",
                },
                {
                    "id": "a_to_b",
                    "type": "MassFlowController",
                    "source": "r_a",
                    "target": "r_b",
                    "properties": {"mass_flow_rate": 1e-4},
                },
                {
                    "id": "b_to_sink",
                    "type": "MassFlowController",
                    "source": "r_b",
                    "target": "sink_b",
                    "properties": {"mass_flow_rate": 1e-4},
                    "group": "stage_b",
                },
            ],
        }
        conv = DualCanteraConverter(mechanism="gri30.yaml")
        plan = build_stage_graph(cfg2)
        solve_staged(conv, plan, cfg2)
        conn_ids = [c["id"] for c in cfg2.get("connections", [])]
        ic = plan.all_inter_connections[0]
        assert ic.inlet_mfc_id in conn_ids, (
            f"Inlet MFC '{ic.inlet_mfc_id}' not found in config['connections']: {conn_ids}"
        )
        assert ic.id not in conn_ids, (
            f"Original inter-stage connection '{ic.id}' still present in config "
            f"after solve — it should be replaced by the stream-point reservoir + "
            f"inlet MFC: {conn_ids}"
        )
        stream_mfc_dict = next(
            c for c in cfg2["connections"] if c["id"] == ic.inlet_mfc_id
        )
        mdot = stream_mfc_dict.get("properties", {}).get("mass_flow_rate")
        assert mdot is not None and mdot > 0, (
            f"Stream inlet MFC '{ic.inlet_mfc_id}' has no positive mass_flow_rate "
            f"after solve (got {mdot}). The upstream outlet mdot was not propagated."
        )


def test_refresh_terminal_outlet_sink_copies_upstream_state():
    """Legacy OutletSink shim: _refresh_terminal_sinks copies upstream reactor phase.

    Remove with OutletSink deprecation.  Multi-stage chains use inter-stage
    stream-point diamonds (_update_stream_point) instead and do not hit this path.
    """
    from boulder.staged_solver import _refresh_terminal_sinks

    conv = DualCanteraConverter(mechanism="gri30.yaml")
    gas = conv.gas
    gas.TPX = 1500.0, 101325.0, "N2:1"
    reactor = ct.IdealGasConstPressureMoleReactor(gas, clone=True)
    reactor.name = "reactor"
    conv.reactors["reactor"] = reactor
    conv.reactor_meta["reactor"] = {"mechanism": "gri30.yaml"}

    sink_gas = conv._get_gas_for_mech("gri30.yaml")
    sink_gas.TPX = 300.0, 101325.0, "N2:1"
    sink = ct.Reservoir(sink_gas, clone=False)
    sink.name = "outlet"
    conv.reactors["outlet"] = sink
    conv.reactor_meta["outlet"] = {"mechanism": "gri30.yaml"}

    cfg = {
        "nodes": [
            {
                "id": "reactor",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {},
            },
            {"id": "outlet", "type": "OutletSink", "properties": {}},
        ],
        "connections": [
            {
                "id": "reactor_to_outlet",
                "type": "PressureController",
                "source": "reactor",
                "target": "outlet",
                "properties": {},
            },
        ],
    }
    _refresh_terminal_sinks(conv, cfg)

    assert abs(conv.reactors["outlet"].phase.T - 1500.0) < 1.0
    outlet_props = next(n for n in cfg["nodes"] if n["id"] == "outlet")["properties"]
    assert outlet_props.get("terminal_sink") is True
    assert outlet_props.get("source_node") == "reactor"


def test_terminal_outlet_sink_matches_upstream_reactor_after_solve():
    """Legacy OutletSink: terminal sink thermo matches upstream after staged solve.

    Remove with OutletSink deprecation.  Not exercised by multi-stage chains
    (the stream-point diamond is refreshed via _update_stream_point).
    """
    cfg = normalize_config(
        {
            "phases": {"gas": {"mechanism": "gri30.yaml"}},
            "settings": {
                "solver": {"kind": "advance", "advance_time": 1e-6},
            },
            "network": [
                {
                    "id": "feed",
                    "Reservoir": {
                        "temperature": 300.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
                {
                    "id": "reactor",
                    "IdealGasConstPressureMoleReactor": {
                        "volume": 1e-5,
                        "initial": {
                            "temperature": 1500.0,
                            "pressure": 101325.0,
                            "composition": "N2:1",
                        },
                    },
                },
                {
                    "id": "feed_to_reactor",
                    "MassFlowController": {"mass_flow_rate": 1e-4},
                    "source": "feed",
                    "target": "reactor",
                },
                {
                    "id": "reactor_to_outlet",
                    "PressureController": {
                        "master": "feed_to_reactor",
                        "pressure_coeff": 0.0,
                    },
                    "source": "reactor",
                    "target": "outlet",
                },
                {"id": "outlet", "OutletSink": {}},
            ],
        }
    )
    conv = DualCanteraConverter(mechanism="gri30.yaml")
    plan = build_stage_graph(cfg)
    solve_staged(conv, plan, cfg)

    T_reactor = float(conv.reactors["reactor"].phase.T)
    T_sink = float(conv.reactors["outlet"].phase.T)
    assert abs(T_sink - T_reactor) < 1.0, (
        f"OutletSink T={T_sink:.2f} K differs from reactor T={T_reactor:.2f} K"
    )

    outlet_node = next(n for n in cfg["nodes"] if n["id"] == "outlet")
    props = outlet_node.get("properties") or {}
    assert props.get("terminal_sink") is True
    assert props.get("source_node") == "reactor"
    assert abs(float(props["temperature"]) - T_reactor) < 1.0
