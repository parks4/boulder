"""Unit tests for Boulder application components."""

import json

import pytest

from boulder.config import get_initial_config
from boulder.utils import config_to_cyto_elements


@pytest.mark.unit
class TestBoulderConfig:
    """Unit tests for configuration functionality."""

    def test_get_initial_config_structure(self):
        """Test initial configuration has correct structure."""
        config = get_initial_config()

        assert isinstance(config, dict)
        assert "components" in config
        assert "connections" in config
        assert isinstance(config["components"], list)
        assert isinstance(config["connections"], list)

    def test_get_initial_config_components(self):
        """Test initial config components have required fields."""
        config = get_initial_config()

        for component in config["components"]:
            assert "id" in component
            assert "type" in component
            assert "properties" in component
            assert isinstance(component["properties"], dict)


@pytest.mark.unit
class TestBoulderUtils:
    """Unit tests for utility functions."""

    def test_config_to_cyto_elements_empty_config(self):
        """Test config conversion with empty config."""
        config = {"components": [], "connections": []}
        elements = config_to_cyto_elements(config)
        assert elements == []

    def test_config_to_cyto_elements_with_reactor(self):
        """Test config conversion with a single reactor."""
        config = {
            "components": [
                {
                    "id": "reactor1",
                    "type": "IdealGasReactor",
                    "properties": {"temperature": 300, "pressure": 101325},
                }
            ],
            "connections": [],
        }

        elements = config_to_cyto_elements(config)

        assert len(elements) == 1
        node = elements[0]
        assert node["data"]["id"] == "reactor1"
        assert node["data"]["type"] == "IdealGasReactor"
        assert "classes" in node

    def test_config_to_cyto_elements_with_connection(self):
        """Test config conversion with reactor and connection."""
        config = {
            "components": [
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
            "components": [
                {"id": "existing-reactor", "type": "IdealGasReactor", "properties": {}}
            ]
        }

        # Test adding reactor with existing ID
        new_reactor_id = "existing-reactor"
        has_duplicate = any(
            comp["id"] == new_reactor_id for comp in config["components"]
        )
        assert has_duplicate is True

        # Test adding reactor with new ID
        new_reactor_id = "new-reactor"
        has_duplicate = any(
            comp["id"] == new_reactor_id for comp in config["components"]
        )
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
            '{"components": [{"id": "r1", "type": "IdealGasReactor", "properties": {}}], '
            '"connections": []}'
        )
        try:
            parsed = json.loads(valid_json)
            assert "components" in parsed
            assert "connections" in parsed
            assert len(parsed["components"]) == 1
        except json.JSONDecodeError:
            pytest.fail("Valid JSON should parse successfully")

        # Test invalid JSON
        invalid_json = '{"components": [}, "connections": []}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid_json)


@pytest.mark.unit
class TestBoulderLayout:
    """Unit tests for layout components."""

    def test_layout_generation(self):
        """Test that layout can be generated with initial config."""
        from boulder.layout import get_layout
        from boulder.styles import CYTOSCAPE_STYLESHEET

        initial_config = get_initial_config()
        layout = get_layout(initial_config, CYTOSCAPE_STYLESHEET)

        assert layout is not None
        # Layout should be a Dash component
        assert hasattr(layout, "children")

    def test_layout_contains_required_components(self):
        """Test that layout contains required UI components."""
        from boulder.layout import get_layout
        from boulder.styles import CYTOSCAPE_STYLESHEET

        initial_config = get_initial_config()
        layout = get_layout(initial_config, CYTOSCAPE_STYLESHEET)

        # Convert layout to string to check for component IDs
        layout_str = str(layout)

        # Check for key component IDs
        required_ids = [
            "reactor-graph",
            "add-reactor-modal",
            "open-reactor-modal",
            "notification-toast",
            "current-config",
        ]

        for component_id in required_ids:
            assert component_id in layout_str, (
                f"Component {component_id} not found in layout"
            )


@pytest.mark.integration
class TestBoulderIntegration:
    """Integration tests for Boulder application."""

    def test_app_creation(self):
        """Test that the app can be created without errors."""
        from boulder.app import app

        assert app is not None
        assert hasattr(app, "layout")
        assert hasattr(app, "callback_map")

    def test_callbacks_registration(self):
        """Test that all callbacks can be registered."""
        from boulder.app import app

        # App should have callbacks registered during import
        assert len(app.callback_map) > 0

        # Check for specific callback patterns
        callback_ids = [str(cb) for cb in app.callback_map.keys()]

        # Should have callbacks for reactor management
        has_reactor_callback = any("add-reactor" in cb_id for cb_id in callback_ids)
        assert has_reactor_callback, "No add-reactor callback found"

    def test_stylesheet_loading(self):
        """Test that cytoscape stylesheet loads correctly."""
        from boulder.styles import CYTOSCAPE_STYLESHEET

        assert isinstance(CYTOSCAPE_STYLESHEET, list)
        assert len(CYTOSCAPE_STYLESHEET) > 0

        # Each style should have selector and style properties
        for style in CYTOSCAPE_STYLESHEET:
            assert "selector" in style
            assert "style" in style
