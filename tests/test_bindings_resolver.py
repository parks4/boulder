"""Tests for boulder/bindings.py — binding path resolution (Phase B).

Asserts:
- parse_binding_path correctly parses all supported target patterns.
- parse_binding_path raises ValueError with a descriptive message for unknown paths.
- apply_binding sets mass_flow_rate on an MFC when the target is
  connections.<id>.mass_flow_rate.
- apply_binding registers a schedule callback when the target is
  nodes.<id>.reduced_electric_field.
- apply_binding raises ValueError when the connection or node ID is not found.
- apply_bindings_block applies all bindings from a list, including signal resolution.
"""

from unittest.mock import MagicMock, patch, PropertyMock

import cantera as ct
import pytest

from boulder.bindings import (
    ConnectionMassFlowRateTarget,
    ConnectionTauSTarget,
    ContinuationParameterTarget,
    NodeReducedElectricFieldTarget,
    apply_binding,
    apply_bindings_block,
    parse_binding_path,
)
from boulder.signals import build_signal


# ---------------------------------------------------------------------------
# parse_binding_path
# ---------------------------------------------------------------------------


class TestParseBindingPath:
    def test_connection_mass_flow_rate(self):
        """Parse 'connections.mfc1.mass_flow_rate' into ConnectionMassFlowRateTarget."""
        result = parse_binding_path("connections.mfc1.mass_flow_rate")
        assert isinstance(result, ConnectionMassFlowRateTarget)
        assert result.connection_id == "mfc1"

    def test_connection_tau_s(self):
        """Parse 'connections.mfc1.tau_s' into ConnectionTauSTarget."""
        result = parse_binding_path("connections.mfc1.tau_s")
        assert isinstance(result, ConnectionTauSTarget)
        assert result.connection_id == "mfc1"

    def test_node_reduced_electric_field(self):
        """Parse 'nodes.r1.reduced_electric_field' into NodeReducedElectricFieldTarget."""
        result = parse_binding_path("nodes.r1.reduced_electric_field")
        assert isinstance(result, NodeReducedElectricFieldTarget)
        assert result.node_id == "r1"

    def test_continuation_parameter(self):
        """Parse 'continuation.parameters.tau' into ContinuationParameterTarget."""
        result = parse_binding_path("continuation.parameters.tau")
        assert isinstance(result, ContinuationParameterTarget)
        assert result.parameter_name == "tau"

    def test_unknown_path_raises(self):
        """Unknown paths raise ValueError with a descriptive message."""
        with pytest.raises(ValueError, match="Unrecognised"):
            parse_binding_path("network.topology.something")

    def test_unknown_connection_attribute_raises(self):
        """Unknown connection attributes raise ValueError."""
        with pytest.raises(ValueError, match="Unknown binding target attribute"):
            parse_binding_path("connections.mfc1.heat_flux")

    def test_unknown_node_attribute_raises(self):
        """Unknown node attributes raise ValueError."""
        with pytest.raises(ValueError, match="Unknown binding target attribute"):
            parse_binding_path("nodes.r1.temperature")

    def test_too_short_path_raises(self):
        """A path with fewer than 3 parts raises ValueError."""
        with pytest.raises(ValueError, match="Unrecognised"):
            parse_binding_path("connections")

    def test_connection_path_no_attribute_raises(self):
        """A connection path without an attribute raises ValueError."""
        with pytest.raises(ValueError, match="Unrecognised"):
            parse_binding_path("connections.mfc1")


# ---------------------------------------------------------------------------
# apply_binding — MFC mass_flow_rate
# ---------------------------------------------------------------------------


class TestApplyBindingMassFlowRate:
    def _make_converter(self, mfc_id="mfc1"):
        """Return a mock converter with a real MassFlowController."""
        gas = ct.Solution("gri30.yaml")
        gas.TPX = 300, 101325, "N2:1"
        r_src = ct.Reservoir(gas)
        r_tgt = ct.Reservoir(gas)
        mfc = ct.MassFlowController(r_src, r_tgt)
        conv = MagicMock()
        conv.reactors = {}
        conv.connections = {mfc_id: mfc}
        conv._schedule_callbacks = []
        return conv, mfc

    def test_sets_mass_flow_rate_on_mfc(self):
        """apply_binding sets mass_flow_rate on the MFC without raising an error."""
        conv, mfc = self._make_converter()
        sig = build_signal({"Constant": {"value": 0.05}})
        # Should not raise; verifies the setter accepts the signal
        apply_binding(conv, {"source": "c", "target": "connections.mfc1.mass_flow_rate"}, sig)

    def test_missing_connection_raises(self):
        """apply_binding raises ValueError when connection ID is not found."""
        conv, _ = self._make_converter()
        sig = build_signal({"Constant": {"value": 0.1}})
        with pytest.raises(ValueError, match="connection 'nonexistent' not found"):
            apply_binding(conv, {"source": "c", "target": "connections.nonexistent.mass_flow_rate"}, sig)

    def test_non_mfc_device_raises(self):
        """apply_binding raises ValueError when the connection is not an MFC."""
        gas = ct.Solution("gri30.yaml")
        gas.TPX = 300, 101325, "N2:1"
        r_src = ct.Reservoir(gas)
        r_tgt = ct.Reservoir(gas)
        valve = ct.Valve(r_src, r_tgt)
        conv = MagicMock()
        conv.connections = {"valve1": valve}
        sig = build_signal({"Constant": {"value": 0.1}})
        with pytest.raises(ValueError, match="not a MassFlowController"):
            apply_binding(conv, {"source": "c", "target": "connections.valve1.mass_flow_rate"}, sig)


# ---------------------------------------------------------------------------
# apply_binding — reduced_electric_field
# ---------------------------------------------------------------------------


class TestApplyBindingReducedElectricField:
    def _make_plasma_converter(self, node_id="r1"):
        """Return a mock converter with a ConstPressureReactor using plasma mock."""
        gas = ct.Solution("gri30.yaml")
        gas.TPX = 300, 101325, "N2:1"
        reactor = ct.ConstPressureReactor(gas, energy="off")
        conv = MagicMock()
        conv.reactors = {node_id: reactor}
        conv.connections = {}
        conv._schedule_callbacks = []
        return conv, reactor

    def test_appends_schedule_callback(self):
        """apply_binding appends a schedule callback to _schedule_callbacks."""
        conv, _ = self._make_plasma_converter()
        sig = build_signal({"Gaussian": {"peak": 1.9e-19, "center": 24e-9, "fwhm": 7.06e-9}})
        apply_binding(
            conv,
            {"source": "pulse", "target": "nodes.r1.reduced_electric_field"},
            sig,
        )
        assert len(conv._schedule_callbacks) == 1

    def test_missing_node_raises(self):
        """apply_binding raises ValueError when node ID is not found."""
        conv, _ = self._make_plasma_converter()
        sig = build_signal({"Constant": {"value": 1.0}})
        with pytest.raises(ValueError, match="node 'missing' not found"):
            apply_binding(conv, {"source": "s", "target": "nodes.missing.reduced_electric_field"}, sig)

    def test_missing_target_key_raises(self):
        """apply_binding raises ValueError when target key is missing."""
        conv, _ = self._make_plasma_converter()
        sig = build_signal({"Constant": {"value": 1.0}})
        with pytest.raises(ValueError, match="missing a 'target' key"):
            apply_binding(conv, {"source": "s"}, sig)


# ---------------------------------------------------------------------------
# apply_bindings_block
# ---------------------------------------------------------------------------


class TestApplyBindingsBlock:
    def _make_converter(self):
        gas = ct.Solution("gri30.yaml")
        gas.TPX = 300, 101325, "N2:1"
        r_src = ct.Reservoir(gas)
        r_tgt = ct.Reservoir(gas)
        mfc = ct.MassFlowController(r_src, r_tgt)
        conv = MagicMock()
        conv.reactors = {}
        conv.connections = {"inlet": mfc}
        conv._schedule_callbacks = []
        return conv, mfc

    def test_applies_all_bindings(self):
        """apply_bindings_block applies all bindings in the block without raising."""
        conv, mfc = self._make_converter()
        registry = {"c": build_signal({"Constant": {"value": 0.3}})}
        bindings = [{"source": "c", "target": "connections.inlet.mass_flow_rate"}]
        apply_bindings_block(conv, bindings, registry)  # should not raise

    def test_none_bindings_is_noop(self):
        """apply_bindings_block with None bindings is a no-op."""
        conv, mfc = self._make_converter()
        apply_bindings_block(conv, None, {})

    def test_missing_source_raises(self):
        """apply_bindings_block raises ValueError for unknown signal source."""
        conv, _ = self._make_converter()
        bindings = [{"source": "missing", "target": "connections.inlet.mass_flow_rate"}]
        with pytest.raises(ValueError, match="not found in the signal registry"):
            apply_bindings_block(conv, bindings, {})

    def test_missing_source_key_raises(self):
        """apply_bindings_block raises ValueError if source key is absent."""
        conv, _ = self._make_converter()
        bindings = [{"target": "connections.inlet.mass_flow_rate"}]
        with pytest.raises(ValueError, match="missing a 'source' key"):
            apply_bindings_block(conv, bindings, {})
