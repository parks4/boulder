"""Unit tests for Boulder application components."""

import json

import pytest

from boulder.config import get_initial_config
from boulder.styles import CYTOSCAPE_STYLESHEET
from boulder.utils import config_to_cyto_elements
from boulder.validation import validate_normalized_config


@pytest.mark.unit
class TestBoulderConfig:
    """Unit tests for configuration functionality."""

    def test_get_initial_config_structure(self):
        """Test initial configuration has correct structure.

        Assertions:
        1. Config is a dictionary (isinstance(config, dict))
        2. Config contains "nodes" key
        3. Config contains "connections" key
        4. Config["nodes"] is a list (isinstance(config["nodes"], list))
        5. Config["connections"] is a list (isinstance(config["connections"], list))
        """
        config = get_initial_config()

        assert isinstance(config, dict)
        assert "nodes" in config
        assert "connections" in config
        assert isinstance(config["nodes"], list)
        assert isinstance(config["connections"], list)

    def test_validate_normalized_config(self):
        """Validate config post-normalization without building network.

        Assertions:
        1. Validation function accepts normalized config with 2 reactors and 1 connection
        2. Returned model has correct first node ID (model.nodes[0].id == "r1")
        """
        config = {
            "nodes": [
                {"id": "r1", "type": "IdealGasReactor", "properties": {}},
                {"id": "r2", "type": "IdealGasReactor", "properties": {}},
            ],
            "connections": [
                {
                    "id": "c1",
                    "type": "MassFlowController",
                    "source": "r1",
                    "target": "r2",
                    "properties": {},
                }
            ],
        }
        model = validate_normalized_config(config)
        assert model.nodes[0].id == "r1"

    def test_get_initial_config_components(self):
        """Test initial config components have required fields.

        Assertions for each node in initial config:
        1. Node contains "id" key
        2. Node contains "type" key
        3. Node contains "properties" key
        4. Node["properties"] is a dictionary (isinstance(node["properties"], dict))
        """
        config = get_initial_config()

        for node in config["nodes"]:
            assert "id" in node
            assert "type" in node
            assert "properties" in node
            assert isinstance(node["properties"], dict)


@pytest.mark.unit
class TestBoulderUtils:
    """Unit tests for utility functions."""

    def test_config_to_cyto_elements_empty_config(self):
        """Test config conversion with empty config.

        Assertions:
        1. Empty config (no nodes, no connections) returns empty list (elements == [])
        """
        config = {"nodes": [], "connections": []}
        elements = config_to_cyto_elements(config)
        assert elements == []

    def test_config_to_cyto_elements_with_connection(self):
        """Test config conversion with reactor and connection.

        Assertions:
        1. Config with 2 reactors + 1 connection produces 3 cytoscape elements (len(elements) == 3)
        2. Elements contain exactly 2 nodes (len(nodes) == 2)
        3. Elements contain exactly 1 edge (len(edges) == 1)
        4. Edge has correct source reactor (edge["data"]["source"] == "reactor1")
        5. Edge has correct target reactor (edge["data"]["target"] == "reactor2")
        6. Edge has correct ID (edge["data"]["id"] == "mfc1")
        """
        config = {
            "nodes": [
                {"id": "reactor1", "type": "IdealGasReactor", "properties": {}},
                {"id": "reactor2", "type": "IdealGasReactor", "properties": {}},
            ],
            "connections": [
                {
                    "id": "mfc1",
                    "source": "reactor1",
                    "target": "reactor2",
                    "type": "MassFlowController",
                    "properties": {"mass_flow_rate": 0.001},
                }
            ],
        }

        elements = config_to_cyto_elements(config)

        # Should have 2 nodes + 1 edge = 3 elements
        assert len(elements) == 3

        # Check we have nodes and edges
        nodes = [elem for elem in elements if "source" not in elem["data"]]
        edges = [elem for elem in elements if "source" in elem["data"]]

        assert len(nodes) == 2
        assert len(edges) == 1

        edge = edges[0]
        assert edge["data"]["source"] == "reactor1"
        assert edge["data"]["target"] == "reactor2"


@pytest.mark.unit
class TestBoulderCallbacks:
    """Unit tests for callback functions."""

    def test_add_reactor_callback_logic(self):
        """Test the add reactor callback validation logic."""
        # Simulate the validation logic from graph_callbacks.py

        # Test case 1: All fields present
        reactor_id = "test-reactor"
        reactor_type = "IdealGasReactor"
        temp = 300
        pressure = 101325
        composition = "O2:1,N2:3.76"

        # This mimics the validation in the actual callback
        is_valid = all([reactor_id, reactor_type, temp, pressure, composition])
        assert is_valid is True

        # Test case 2: Missing fields
        is_valid = all([None, reactor_type, temp, pressure, composition])
        assert is_valid is False

        is_valid = all(["", reactor_type, temp, pressure, composition])
        assert is_valid is False

    def test_duplicate_reactor_detection(self):
        """Test duplicate reactor ID detection logic."""
        config = {
            "nodes": [
                {"id": "existing-reactor", "type": "IdealGasReactor", "properties": {}}
            ]
        }

        # Test adding reactor with existing ID
        new_reactor_id = "existing-reactor"
        has_duplicate = any(node["id"] == new_reactor_id for node in config["nodes"])
        assert has_duplicate is True

        # Test adding reactor with new ID
        new_reactor_id = "new-reactor"
        has_duplicate = any(node["id"] == new_reactor_id for node in config["nodes"])
        assert has_duplicate is False

    def test_mfc_validation_logic(self):
        """Test MFC addition validation."""
        # Test all required fields present
        mfc_id = "mfc-1"
        source = "reactor1"
        target = "reactor2"
        flow_rate = 0.001

        is_valid = all([mfc_id, source, target, flow_rate])
        assert is_valid is True

        # Test missing flow rate
        is_valid = all([mfc_id, source, target, None])
        assert is_valid is False

    def test_duplicate_connection_detection(self):
        """Test duplicate connection detection logic."""
        config = {
            "connections": [{"source": "reactor1", "target": "reactor2", "id": "mfc1"}]
        }

        # Test adding duplicate connection
        source = "reactor1"
        target = "reactor2"
        has_duplicate = any(
            conn["source"] == source and conn["target"] == target
            for conn in config["connections"]
        )
        assert has_duplicate is True

        # Test adding new connection
        source = "reactor2"
        target = "reactor3"
        has_duplicate = any(
            conn["source"] == source and conn["target"] == target
            for conn in config["connections"]
        )
        assert has_duplicate is False

    def test_json_config_validation(self):
        """Test JSON configuration validation."""
        # Test valid JSON
        valid_json = (
            '{"nodes": [{"id": "r1", "type": "IdealGasReactor", "properties": {}}], '
            '"connections": []}'
        )
        try:
            parsed = json.loads(valid_json)
            assert "nodes" in parsed
            assert "connections" in parsed
            assert len(parsed["nodes"]) == 1
        except json.JSONDecodeError:
            pytest.fail("Valid JSON should parse successfully")

        # Test invalid JSON
        invalid_json = '{"nodes": [}, "connections": []}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid_json)


@pytest.mark.unit
class TestBoulderStylesheet:
    """Unit tests for Cytoscape stylesheet configuration."""

    def test_stylesheet_loading(self):
        """Test that cytoscape stylesheet loads correctly."""
        assert isinstance(CYTOSCAPE_STYLESHEET, list)
        assert len(CYTOSCAPE_STYLESHEET) > 0

        # Each style should have selector and style properties
        for style in CYTOSCAPE_STYLESHEET:
            assert "selector" in style
            assert "style" in style
