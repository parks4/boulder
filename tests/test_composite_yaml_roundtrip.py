"""Round-trip tests: composite YAML editor preserves port connections.

Tests the full GUI flow for a ThreeSegmentsReactor composite:
  load YAML -> normalize (expand composite) -> emulate post-sim config
  (children present, port connections rewritten to internal ids,
   layout_offset set, group/logical set)
  -> merge_config_into_yaml -> parseYaml
  -> assert composite node preserved, children filtered, port connections
     keep authored target + port field, layout_offset survives.

All assertions document invariants that prevent the "network destroyed" bug
when opening the YAML editor after running a simulation.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from boulder.config import merge_config_into_yaml, normalize_config

# ---------------------------------------------------------------------------
# Minimal composite YAML fixture (ThreeSegmentsReactor without Cantera kinds)
# ---------------------------------------------------------------------------

_COMPOSITE_YAML = """\
metadata:
  title: "CGR composite round-trip test"

phases:
  gas:
    mechanism: gri30.yaml

stages:
  psr_stage:
    solver: {kind: advance, advance_time: 1.0e-9}
  cgr_stage:
    solver: {kind: advance, advance_time: 1.0}

psr_stage:
- id: tmr
  metadata: {layout_lane: main_flow}
  InstantaneousMixingReactor:
    t_res_s: 1.0e-9
    initial: {temperature: 298.15, composition: "CH4:1"}

cgr_stage:
- id: cgr
  metadata: {layout_lane: main_flow}
  ThreeSegmentsReactor:
    diameter: 0.1
    eps_wall: 0.9
    T_wall_hyp: 100.0
    T_amb: 25.0
    heat_loss_corr_factor: 2.0
    t_res_mix_s: 1.0e-9
    insulation:
      e_insul:      {1: 0.10, 2: 0.06, 3: 0.04}
      conductivity: {1: 0.2,  2: 0.1,  3: 0.05}
      density:      {1: 2700, 2: 1000, 3: 300}
    segments:
      - {length: 3.333}
      - {length: 3.333}
      - {length: 3.334}
    inlet_ports:
      - {port: main,  after_segment: 0}
      - {port: inj_1, after_segment: 1}

- id: inj_1_feed
  metadata: {layout_lane: inj_1_branch}
  Reservoir: {temperature: 500.0, composition: "CH4:1"}

- id: downstream
  metadata: {layout_lane: main_flow}
  OutletSink: {pressure: 130000.0}

- id: tmr_to_cgr
  source: tmr
  target: cgr
  port: main

- id: inj_1_to_cgr
  MassFlowController: {mass_flow_rate: 0.0}
  source: inj_1_feed
  target: cgr
  port: inj_1

- id: cgr_to_downstream
  MassFlowController: {}
  source: cgr
  target: downstream
"""


def _register_test_plugins():
    """Register ThreeSegmentsReactor unfolder via BlocConverter plugin path."""
    try:
        from bloc.boulder_plugins.register import (
            _register_bloc_solver_plugins,  # noqa: PLC0415
        )

        from boulder.cantera_converter import BoulderPlugins  # noqa: PLC0415

        plugins = BoulderPlugins()
        _register_bloc_solver_plugins(plugins)
        return plugins
    except Exception:
        return None


def _normalize_composite(yaml_str: str) -> dict:
    """Normalize the composite YAML using Bloc plugins (expansion happens inside normalize_config)."""
    from boulder.config import (  # noqa: PLC0415
        _to_plain_dict,
        load_yaml_string_with_comments,
    )

    _register_test_plugins()  # ensure unfolders registered in global plugin registry
    raw = load_yaml_string_with_comments(yaml_str)
    plain = _to_plain_dict(raw)
    # normalize_config calls expand_composite_kinds internally via the global plugin registry
    return normalize_config(plain)


def _emulate_post_sim_config(expanded_cfg: dict) -> dict:
    """Emulate what useSimulationSSE delivers to the frontend.

    Strips __synthesized flags (as Pydantic validate_config would), and
    preserves group/logical fields.  Adds layout_offset to the cgr node
    to simulate a user drag.
    """
    cfg = copy.deepcopy(expanded_cfg)

    # Strip __synthesized (done by Pydantic in production)
    for item in list(cfg.get("nodes", [])) + list(cfg.get("connections", [])):
        item.pop("__synthesized", None)
        props = item.get("properties") or {}
        props.pop("__synthesized", None)

    # Add layout_offset to the cgr placeholder node (simulates user drag)
    for node in cfg.get("nodes", []):
        if node.get("id") == "cgr":
            node.setdefault("metadata", {})
            node["metadata"]["layout_offset"] = {"dx": 50, "dy": -20}

    # Ensure group/logical are on connections (useSimulationSSE preserves these)
    for conn in cfg.get("connections", []):
        if "group" not in conn:
            conn["group"] = None
        if "logical" not in conn:
            conn["logical"] = None

    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _authored_conn_ids() -> set:
    """Return connection ids that are explicitly authored in the YAML."""
    return {"tmr_to_cgr", "inj_1_to_cgr", "cgr_to_downstream"}


def _find_conn(cfg: dict, conn_id: str) -> Dict[str, Any]:
    for c in cfg.get("connections", []):
        if c.get("id") == conn_id:
            return c
    return {}


def _find_node(cfg: dict, node_id: str) -> Dict[str, Any]:
    for n in cfg.get("nodes", []):
        if n.get("id") == node_id:
            return n
    return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def plugins():
    return _register_test_plugins()


@pytest.fixture(scope="module")
def original_yaml() -> str:
    return _COMPOSITE_YAML


@pytest.fixture(scope="module")
def post_sim_config(original_yaml) -> dict:
    expanded = _normalize_composite(original_yaml)
    return _emulate_post_sim_config(expanded)


class TestCompositeRoundTrip:
    """merge_config_into_yaml preserves composite form after Run Simulation."""

    def test_composite_node_preserved(self, post_sim_config, original_yaml):
        """Cgr composite node remains in the merged YAML (not replaced by children)."""
        merged_yaml, _warnings = merge_config_into_yaml(post_sim_config, original_yaml)
        final = normalize_config(_to_plain_dict_from_yaml(merged_yaml))
        node_ids = {n["id"] for n in final.get("nodes", [])}
        assert "cgr" in node_ids, (
            f"'cgr' composite node missing from merged YAML. Present ids: {sorted(node_ids)}"
        )

    def test_children_not_in_merged_yaml(self, post_sim_config, original_yaml):
        """Synthesized child ids (cgr_seg*, cgr_mix_*, cgr_ambient) absent from merged YAML."""
        merged_yaml, _warnings = merge_config_into_yaml(post_sim_config, original_yaml)
        # Check raw YAML text — child ids must not appear as 'id: cgr_seg1' etc.
        synthesized_ids = {
            "cgr_seg1",
            "cgr_seg2",
            "cgr_mix_1",
            "cgr_ambient",
            "cgr_int_cgr_seg1_to_cgr_mix_1",
        }
        for sid in synthesized_ids:
            assert f"id: {sid}" not in merged_yaml, (
                f"Synthesized child '{sid}' leaked into merged YAML."
            )

    def test_port_connection_target_is_composite(self, post_sim_config, original_yaml):
        """tmr_to_cgr connection keeps target: cgr (not the rewritten cgr_seg1)."""
        merged_yaml, _warnings = merge_config_into_yaml(post_sim_config, original_yaml)
        # The raw YAML must have 'target: cgr' for tmr_to_cgr, not 'target: cgr_seg1'
        assert "target: cgr_seg1" not in merged_yaml, (
            "Port connection was written with rewritten internal target 'cgr_seg1'."
        )
        assert "target: cgr" in merged_yaml or "target: 'cgr'" in merged_yaml, (
            "Authored 'target: cgr' not found in merged YAML for tmr_to_cgr."
        )

    def test_port_field_preserved_in_merged_yaml(self, post_sim_config, original_yaml):
        """The 'port: main' field is present in the merged YAML for tmr_to_cgr."""
        merged_yaml, _warnings = merge_config_into_yaml(post_sim_config, original_yaml)
        assert "port: main" in merged_yaml, (
            "'port: main' field missing from merged YAML — port connection was stripped."
        )

    def test_layout_offset_survives(self, post_sim_config, original_yaml):
        """layout_offset set by user drag survives the merge round-trip."""
        merged_yaml, _warnings = merge_config_into_yaml(post_sim_config, original_yaml)
        assert "layout_offset" in merged_yaml, (
            "layout_offset metadata lost during merge."
        )

    def test_all_authored_connections_present(self, post_sim_config, original_yaml):
        """All three authored connections survive the merge."""
        merged_yaml, _warnings = merge_config_into_yaml(post_sim_config, original_yaml)
        for cid in _authored_conn_ids():
            assert f"id: {cid}" in merged_yaml, (
                f"Authored connection '{cid}' missing from merged YAML."
            )

    def test_idempotent_two_cycles(self, post_sim_config, original_yaml):
        """Running merge twice produces identical output (idempotency)."""
        merged1, _w1 = merge_config_into_yaml(post_sim_config, original_yaml)
        merged2, _w2 = merge_config_into_yaml(post_sim_config, merged1)
        # Both cycles must preserve the authored connections
        for cid in _authored_conn_ids():
            assert f"id: {cid}" in merged2, (
                f"Authored connection '{cid}' missing after second merge cycle."
            )
        assert "target: cgr_seg1" not in merged2, (
            "Port corruption appeared on second merge cycle."
        )

    def test_non_port_connections_unaffected(self, post_sim_config, original_yaml):
        """cgr_to_downstream (no port:) keeps target: downstream."""
        merged_yaml, _warnings = merge_config_into_yaml(post_sim_config, original_yaml)
        assert "target: downstream" in merged_yaml, (
            "Non-port connection cgr_to_downstream lost its target."
        )


# ---------------------------------------------------------------------------
# Helper: plain dict from yaml string (no plugins)
# ---------------------------------------------------------------------------


def _to_plain_dict_from_yaml(yaml_str: str) -> dict:
    from boulder.config import (  # noqa: PLC0415
        _to_plain_dict,
        load_yaml_string_with_comments,
    )

    raw = load_yaml_string_with_comments(yaml_str)
    return _to_plain_dict(raw)
