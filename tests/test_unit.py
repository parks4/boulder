"""Unit tests for Boulder application components."""

import json

import pytest

from boulder.config import get_initial_config, normalize_config, validate_config
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

    def test_metadata_gui_app_title_round_trip(self):
        """``metadata.gui_app_title`` validates and appears on the validated dict.

        Assertions:
        1. Normalized config with ``gui_app_title`` passes ``validate_config``
        2. Returned metadata contains the same non-empty string
        """
        raw = {
            "metadata": {"gui_app_title": "MyApp", "description": "test"},
            "nodes": [{"id": "r1", "type": "IdealGasReactor", "properties": {}}],
            "connections": [],
        }
        validated = validate_config(normalize_config(raw))
        assert validated["metadata"]["gui_app_title"] == "MyApp"

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
