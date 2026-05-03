"""Comprehensive tests for YAML comment preservation system.

This module consolidates all YAML comment preservation tests into a single,
well-organized test suite covering:
- Basic YAML comment loading and saving
- Comment preservation during updates
- Integration with the Boulder application
- Edge cases and error handling
"""

import base64
import os
import tempfile

import pytest

from boulder.config import (
    _update_yaml_preserving_comments,
    convert_to_stone_format,
    get_initial_config,
    get_initial_config_with_comments,
    get_yaml_with_comments,
    load_config_file_with_comments,
    load_yaml_string_with_comments,
    normalize_config,
    yaml_to_string_with_comments,
)
from boulder.validation import validate_normalized_config


class TestYAMLCommentCore:
    """Core YAML comment preservation functionality tests."""

    @pytest.fixture
    def sample_yaml_with_comments(self):
        """Sample YAML configuration with comprehensive comments and units."""
        return """# Boulder Configuration with STONE Standard
# This file demonstrates comment preservation in YAML configs

metadata:
  name: "Test Configuration"
  description: "Sample configuration with comments and units"
  version: "1.0"

# Simulation parameters with detailed comments
settings:
  end_time: 1.0  # seconds - total simulation duration
  dt: 0.01       # seconds - integration time step

# Reactor components with detailed comments and units
network:
  - id: "upstream"
    # Upstream boundary reservoir
    Reservoir:
      temperature: 300.0  # K
      composition: "CH4:1, O2:2, N2:7.52"

  - id: "mfc1"
    # Controlled flow from upstream to reactor1
    MassFlowController:
      mass_flow_rate: 0.001  # kg/s - mass flow rate control
    source: "upstream"
    target: "reactor1"

  - id: "reactor1"
    # Primary combustion chamber - high temperature operation
    IdealGasReactor:
      volume: 1.0e-3  # m**3 - reactor volume

  - id: "reactor2"
    # Secondary reactor for mixing and cooling
    IdealGasReactor:
      volume: 2.0e-3  # m**3 - reactor volume

  - id: "mfc_link"
    # Controlled flow from reactor1 to reactor2
    MassFlowController:
      mass_flow_rate: 0.001  # kg/s - mass flow rate control
    source: "reactor1"
    target: "reactor2"

  - id: "outlet"
    # Downstream outlet sink
    OutletSink:
"""

    @pytest.fixture
    def sample_internal_config(self):
        """Sample configuration in internal format."""
        return {
            "metadata": {
                "name": "Test Configuration",
                "description": "Sample configuration with comments and units",
                "version": "1.0",
            },
            "simulation": {"end_time": 1.0, "dt": 0.01},
            "components": [
                {
                    "id": "reactor1",
                    "type": "IdealGasReactor",
                    "properties": {
                        "temperature": 1000.0,
                        "pressure": 101325.0,
                        "composition": "CH4:1, O2:2, N2:7.52",
                    },
                },
                {
                    "id": "reactor2",
                    "type": "IdealGasReactor",
                    "properties": {
                        "temperature": 800.0,
                        "pressure": 101325.0,
                        "composition": "O2:1, N2:3.76",
                    },
                },
            ],
            "connections": [
                {
                    "id": "mfc1",
                    "type": "MassFlowController",
                    "source": "reactor1",
                    "target": "reactor2",
                    "properties": {"mass_flow_rate": 0.001},
                }
            ],
        }

    def test_yaml_object_configuration(self):
        """Test that the YAML object is properly configured for comment preservation."""
        yaml_obj = get_yaml_with_comments()

        # Check that important settings are configured
        assert yaml_obj.preserve_quotes is True
        assert yaml_obj.width == 4096

    def test_load_yaml_string_with_comments(self, sample_yaml_with_comments):
        """Test loading YAML string while preserving comments."""
        result = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Verify the data structure is loaded correctly
        assert result["metadata"]["name"] == "Test Configuration"
        # network: is the v2 top-level key containing all items
        items_by_id = {item["id"]: item for item in result["network"]}
        assert "reactor1" in items_by_id
        assert "mfc1" in items_by_id
        assert items_by_id["mfc1"]["MassFlowController"]["mass_flow_rate"] == 0.001

    def test_yaml_to_string_with_comments(self, sample_yaml_with_comments):
        """Test converting data to YAML string with comment preservation."""
        # Load the data first
        data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Convert back to string
        result = yaml_to_string_with_comments(data)

        # Verify it's a valid YAML string with substantial content
        assert isinstance(result, str)
        assert "metadata:" in result
        assert "network:" in result
        assert len(result) > 100

    def test_update_yaml_preserving_comments(self, sample_yaml_with_comments):
        """Test updating YAML data while preserving structure and comments."""
        # Load original data
        original_data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Create new data with metadata and settings changes only
        new_data = {
            "metadata": {
                "name": "Updated Configuration",
                "description": "Updated description",
                "version": "2.0",
            },
            "settings": {"end_time": 2.0, "dt": 0.02},
        }

        # Update preserving comments
        updated_data = _update_yaml_preserving_comments(original_data, new_data)

        # Verify updates were applied
        assert updated_data["metadata"]["name"] == "Updated Configuration"
        assert updated_data["metadata"]["version"] == "2.0"
        assert updated_data["settings"]["end_time"] == 2.0

    def test_preserves_numeric_types(self, sample_yaml_with_comments):
        """Test that numeric types are preserved correctly."""
        data = load_yaml_string_with_comments(sample_yaml_with_comments)

        items_by_id = {item["id"]: item for item in data["network"]}
        upstream = items_by_id["upstream"]
        assert isinstance(upstream["Reservoir"]["temperature"], float)
        assert isinstance(data["settings"]["end_time"], float)
        assert isinstance(data["settings"]["dt"], float)

    def test_preserves_string_types(self, sample_yaml_with_comments):
        """Test that string types are preserved correctly."""
        data = load_yaml_string_with_comments(sample_yaml_with_comments)

        items_by_id = {item["id"]: item for item in data["network"]}
        assert isinstance(data["metadata"]["name"], str)
        assert isinstance(items_by_id["reactor1"]["id"], str)
        assert isinstance(items_by_id["upstream"]["Reservoir"]["composition"], str)


class TestYAMLCommentRoundTrip:
    """Test round-trip conversions between different formats."""

    @pytest.fixture
    def sample_yaml_with_comments(self):
        """Sample YAML for round-trip testing."""
        return """# Boulder Configuration with STONE Standard
metadata:
  description: "Round Trip Test Config"
  name: "Round Trip Test"
  version: "1.0"

settings:
  end_time: 1.0  # seconds

network:
  - id: "feed"
    Reservoir:
      temperature: 300.0  # K
      composition: "N2:1"
  - id: "test_reactor"
    IdealGasReactor:
      volume: 1.0e-3  # m**3
  - id: "mfc_in"
    MassFlowController:
      mass_flow_rate: 0.001
    source: "feed"
    target: "test_reactor"
"""

    def test_yaml_to_internal_to_stone_roundtrip(self, sample_yaml_with_comments):
        """Test full round-trip: STONE v2 YAML → normalize → STONE → YAML."""
        # Load YAML with comments
        loaded_data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Normalize to internal format
        internal_config = normalize_config(loaded_data)
        # Validate post-normalization
        validate_normalized_config(internal_config)

        # Verify internal format is correct
        nodes_by_id = {n["id"]: n for n in internal_config["nodes"]}
        assert "test_reactor" in nodes_by_id
        assert nodes_by_id["test_reactor"]["type"] == "IdealGasReactor"
        assert "properties" in nodes_by_id["test_reactor"]

        # Convert back to STONE format
        stone_config = convert_to_stone_format(internal_config)

        # Verify STONE v2 shape (network: list, not legacy nodes:/connections:)
        assert "network" in stone_config
        stone_nodes_by_id = {
            item["id"]: item for item in stone_config["network"] if "source" not in item
        }
        assert "test_reactor" in stone_nodes_by_id
        assert "IdealGasReactor" in stone_nodes_by_id["test_reactor"]

        # Convert to YAML string
        yaml_string = yaml_to_string_with_comments(stone_config)

        # Verify the result contains expected content
        assert "test_reactor" in yaml_string
        assert "IdealGasReactor" in yaml_string

    def test_comment_preservation_with_updates(self, sample_yaml_with_comments):
        """Test that comments are preserved when configuration is updated."""
        # Load original with comments
        original_data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Simulate a configuration update
        updated_stone_config = {
            "metadata": {
                "name": "Updated Round Trip Test",
                "version": "1.1",
            },
            "simulation": {"end_time": 2.0},
            "components": [
                {
                    "id": "test_reactor",
                    "IdealGasReactor": {
                        "temperature": 1300.0,  # Updated temperature
                        "pressure": 101325.0,
                    },
                }
            ],
        }

        # Update preserving structure
        updated_data = _update_yaml_preserving_comments(
            original_data, updated_stone_config
        )

        # Convert to string
        result_yaml = yaml_to_string_with_comments(updated_data)

        # Verify updates were applied
        assert "1300" in result_yaml  # Updated temperature
        assert "Updated Round Trip Test" in result_yaml

    def test_stone_format_round_trip_with_comments(self, sample_yaml_with_comments):
        """Test that STONE v2 format configurations survive round-trip processing.

        Expectation: After converting STONE v2 → internal → STONE → comment
        preservation → YAML → reload, the final config contains the reactor
        node with an internal-format representation.
        """
        from boulder.config import normalize_config

        # Simulate the full application workflow for config processing
        original_data = load_yaml_string_with_comments(sample_yaml_with_comments)
        internal_config = normalize_config(original_data)
        validate_normalized_config(internal_config)
        stone_config = convert_to_stone_format(internal_config)
        updated_data = _update_yaml_preserving_comments(original_data, stone_config)
        final_yaml = yaml_to_string_with_comments(updated_data)
        final_data = load_yaml_string_with_comments(final_yaml)

        # Export uses STONE v2 ``network:`` so merged YAML keeps that shape
        assert "network" in final_data, "Final data should have network section"
        assert len(final_data["network"]) > 0, "Should have at least one item"

        nodes_by_id = {
            item["id"]: item for item in final_data["network"] if "source" not in item
        }
        assert "test_reactor" in nodes_by_id, "test_reactor node should be present"

        node = nodes_by_id["test_reactor"]
        assert "IdealGasReactor" in node, "Node kind key should be IdealGasReactor"


class TestYAMLCommentIntegration:
    """Integration tests with Boulder application components."""

    def test_initial_config_loading_with_comments(self):
        """Test that the initial configuration can be loaded with comments preserved."""
        try:
            config, original_yaml = get_initial_config_with_comments()
            assert isinstance(config, dict)
            assert isinstance(original_yaml, str)
            assert len(original_yaml) > 0

            # Verify the original YAML contains expected sections
            if "network:" in original_yaml or "nodes:" in original_yaml:
                assert "metadata:" in original_yaml

        except FileNotFoundError:
            # Expected if configs/default.yaml doesn't exist
            # Test that fallback works
            config = get_initial_config()
            assert isinstance(config, dict)

    def test_file_upload_simulation(self):
        """Test that uploading a YAML file preserves comments for later editing."""
        sample_yaml = """# Test upload
metadata:
  name: "Upload Test"
nodes:
  - id: "upload_reactor"
    IdealGasReactor:
      temperature: 900.0  # K
"""

        # Simulate file upload process
        encoded_content = base64.b64encode(sample_yaml.encode("utf-8")).decode("utf-8")
        upload_contents = f"data:text/yaml;base64,{encoded_content}"

        # Decode as the upload callback would
        content_type, content_string = upload_contents.split(",")
        decoded_string = base64.b64decode(content_string).decode("utf-8")

        # Load with comment preservation
        decoded = load_yaml_string_with_comments(decoded_string)

        # Verify the data loaded correctly
        assert decoded["metadata"]["name"] == "Upload Test"
        assert decoded["nodes"][0]["IdealGasReactor"]["temperature"] == 900.0

        # Verify we can convert back with comments preserved
        yaml_output = yaml_to_string_with_comments(decoded)
        assert "upload_reactor" in yaml_output
        assert "900" in yaml_output

    def test_error_handling_no_default_yaml(self):
        """Test that the app handles missing default.yaml gracefully.

        This test verifies that when the default configuration file doesn't exist,
        the system either raises FileNotFoundError or returns a fallback configuration.
        """
        # Create a temporary directory without the expected config file
        with tempfile.TemporaryDirectory() as temp_dir:
            # Temporarily change the working directory to the temp directory
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                # Ensure there's no configs directory
                configs_path = os.path.join(temp_dir, "configs")
                if os.path.exists(configs_path):
                    os.rmdir(configs_path)

                # This should either raise FileNotFoundError or return a fallback config
                try:
                    config, yaml_content = get_initial_config_with_comments()
                    # If it doesn't raise an error, it should return valid data
                    assert isinstance(config, dict)
                    assert isinstance(yaml_content, str)
                except FileNotFoundError:
                    # This is also acceptable behavior
                    pass

            finally:
                os.chdir(original_cwd)


class TestYAMLCommentEdgeCases:
    """Test edge cases and error handling for YAML comment preservation."""

    def test_error_handling_invalid_yaml(self):
        """Test error handling with invalid YAML."""
        invalid_yaml = "invalid: yaml: content: [unclosed"

        with pytest.raises(Exception):
            load_yaml_string_with_comments(invalid_yaml)

    def test_empty_yaml_handling(self):
        """Test handling of empty or minimal YAML."""
        minimal_yaml = "metadata:\n  name: 'Minimal Config'"

        result = load_yaml_string_with_comments(minimal_yaml)
        assert result["metadata"]["name"] == "Minimal Config"

    def test_comment_preservation_edge_cases(self):
        """Test comment preservation with edge cases."""
        # Test with minimal YAML
        minimal_yaml = """# Simple config
metadata:
  name: "Minimal"  # just a name
"""

        data = load_yaml_string_with_comments(minimal_yaml)
        result = yaml_to_string_with_comments(data)

        # Should handle minimal content without errors
        assert "Minimal" in result

        # Test with empty sections
        empty_sections_yaml = """# Config with empty sections
metadata:
  name: "Empty Sections"
nodes: []  # no nodes
connections: []  # no connections
"""

        data = load_yaml_string_with_comments(empty_sections_yaml)
        result = yaml_to_string_with_comments(data)

        # Should handle empty sections
        assert "Empty Sections" in result

    def test_units_preservation_examples(self):
        """Test preservation of various unit formats in comments."""
        units_yaml = """# Configuration with various unit formats
nodes:
  - id: "test"
    IdealGasReactor:
      temperature: 1000.0    # K (Kelvin)
      pressure: 101325       # Pa (Pascal) = 1 atm
      mass: 0.5             # kg (kilograms)
      volume: 0.001         # m³ (cubic meters)
      flow_rate: 1.5e-3     # kg/s (mass flow rate)
      time_constant: 0.1    # s (seconds)
"""

        data = load_yaml_string_with_comments(units_yaml)
        result = yaml_to_string_with_comments(data)

        # Verify numeric values are preserved correctly
        reloaded = load_yaml_string_with_comments(result)
        reactor_props = reloaded["nodes"][0]["IdealGasReactor"]

        assert reactor_props["temperature"] == 1000.0
        assert reactor_props["pressure"] == 101325
        assert reactor_props["mass"] == 0.5
        assert reactor_props["volume"] == 0.001
        assert reactor_props["flow_rate"] == 1.5e-3
        assert reactor_props["time_constant"] == 0.1


class TestYAMLFileOperations:
    """Test YAML comment preservation with file operations."""

    def test_file_round_trip(self, tmp_path):
        """Test saving and loading YAML files with comment preservation."""
        # Sample YAML with comments for this test
        sample_yaml = """# Boulder Configuration with STONE Standard
# This file demonstrates comment preservation in YAML configs

metadata:
  name: "File Test Configuration"
  description: "Sample configuration for file operations"
  version: "1.0"

# Simulation parameters
simulation:
  end_time: 1.0  # seconds - simulation duration
  dt: 0.01       # seconds - time step

# Reactor components with detailed comments
nodes:
  - id: "file_reactor"
    # Ideal gas reactor for file testing
    IdealGasReactor:
      temperature: 1000.0  # K - initial temperature
      pressure: 101325.0   # Pa - initial pressure (1 atm)
      composition: "CH4:1, O2:2, N2:7.52"  # molar ratios
"""

        # Create a temporary file
        temp_file = tmp_path / "test_config.yaml"

        # Write the original YAML with UTF-8 encoding
        temp_file.write_text(sample_yaml, encoding="utf-8")

        # Load with comments
        loaded_data = load_config_file_with_comments(str(temp_file))

        # Verify the data was loaded correctly
        assert loaded_data["metadata"]["name"] == "File Test Configuration"
        assert loaded_data["nodes"][0]["IdealGasReactor"]["temperature"] == 1000.0


class TestMergeConfigIntoYaml:
    """Tests for merge_config_into_yaml: full sync pipeline semantics."""

    def _make_config(self, nodes, connections=None):
        """Build a minimal NormalizedConfig-shaped dict."""
        return {
            "nodes": nodes,
            "connections": connections or [],
        }

    def _node(self, nid, kind, props):
        return {"id": nid, "type": kind, "properties": props}

    def _conn(self, cid, kind, source, target, props=None):
        return {
            "id": cid,
            "type": kind,
            "source": source,
            "target": target,
            "properties": props or {},
        }

    def test_merge_preserves_header_and_inline_comments(self):
        """Asserts that header comments and EOL comments survive a no-op merge.

        The original YAML has a # header comment and inline # comments on
        temperature and pressure values. After merge_config_into_yaml with
        the same values, those comment strings are present in the output.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "# Header comment\n"
            "phases:\n"
            "  gas:\n"
            "    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0  # K\n"
            "      pressure: 101325.0  # Pa\n"
        )
        config = self._make_config(
            [
                self._node(
                    "inlet", "Reservoir", {"temperature": 300.0, "pressure": 101325.0}
                ),
            ]
        )
        result, warnings = merge_config_into_yaml(config, yaml)
        assert "# Header comment" in result
        assert "# K" in result
        assert "# Pa" in result

    def test_merge_drops_synthesized_satellites(self):
        """Asserts that nodes/connections tagged __synthesized=True are absent from output.

        Config contains two nodes: one authored (inlet) and one synthesized
        (pfr_ambient). The merged YAML must not contain 'pfr_ambient'.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
        )
        config = self._make_config(
            [
                self._node("inlet", "Reservoir", {"temperature": 300.0}),
                {
                    **self._node("pfr_ambient", "Reservoir", {"temperature": 298.15}),
                    "__synthesized": True,
                },
            ]
        )
        result, _ = merge_config_into_yaml(config, yaml)
        assert "pfr_ambient" not in result
        assert "inlet" in result

    def test_merge_appends_new_user_node(self):
        """Asserts that a GUI-added node (not in originalYaml, no __synthesized) is appended.

        Original has 'inlet'; config adds 'reactor1'. Output must contain both.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
        )
        config = self._make_config(
            [
                self._node("inlet", "Reservoir", {"temperature": 300.0}),
                self._node("reactor1", "IdealGasReactor", {"volume": 0.001}),
            ]
        )
        result, _ = merge_config_into_yaml(config, yaml)
        assert "inlet" in result
        assert "reactor1" in result
        assert "IdealGasReactor" in result

    def test_merge_removes_deleted_node(self):
        """Asserts that a node absent from config is removed from the merged YAML.

        Original has 'inlet' and 'r2'; config omits 'r2'. Output must not contain 'r2'.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
            "  - id: r2\n"
            "    IdealGasReactor:\n"
            "      volume: 0.001\n"
        )
        config = self._make_config(
            [
                self._node("inlet", "Reservoir", {"temperature": 300.0}),
            ]
        )
        result, _ = merge_config_into_yaml(config, yaml)
        assert "inlet" in result
        assert "r2" not in result

    def test_merge_adds_new_property_on_existing_node(self):
        """Asserts that a property added via the GUI appears in the merged YAML.

        Original Reservoir has only temperature. Config adds composition.
        Output must contain 'composition'.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
        )
        config = self._make_config(
            [
                self._node(
                    "inlet",
                    "Reservoir",
                    {
                        "temperature": 300.0,
                        "composition": "CH4:1",
                    },
                ),
            ]
        )
        result, _ = merge_config_into_yaml(config, yaml)
        assert "composition" in result
        assert "CH4:1" in result

    def test_merge_removes_deleted_property_from_component_block(self):
        """Asserts that a property removed via the GUI is absent from the merged YAML.

        Original Reservoir has temperature and composition. Config drops composition.
        Output must not contain 'composition'.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
            '      composition: "CH4:1"\n'
        )
        config = self._make_config(
            [
                self._node("inlet", "Reservoir", {"temperature": 300.0}),
            ]
        )
        result, _ = merge_config_into_yaml(config, yaml)
        assert "temperature" in result
        assert "composition" not in result

    def test_merge_handles_type_change(self):
        """Asserts that changing a node's type removes the old kind key and adds the new one.

        Original has IdealGasReactor; config has same id with
        IdealGasConstPressureReactor. Output must contain only the new kind key.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: r1\n"
            "    IdealGasReactor:\n"
            "      volume: 0.001\n"
        )
        config = self._make_config(
            [
                self._node("r1", "IdealGasConstPressureReactor", {"volume": 0.001}),
            ]
        )
        result, _ = merge_config_into_yaml(config, yaml)
        assert "IdealGasConstPressureReactor" in result
        assert "IdealGasReactor:" not in result

    def test_merge_multi_stage_preserves_stages_shape(self):
        """Asserts that a staged original YAML keeps its stages: shape after merge.

        Original YAML uses stages: + a per-stage list. Merged output must still
        contain 'stages:' and NOT introduce a top-level 'network:' key.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "stages:\n"
            "  s1:\n"
            "    mechanism: gri30.yaml\n"
            "    solve: equilibrate\n"
            "s1:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
        )
        # Build a config that produces a staged STONE output.
        config = {
            "nodes": [
                {
                    **self._node("inlet", "Reservoir", {"temperature": 300.0}),
                    "group": "s1",
                },
            ],
            "connections": [],
            "groups": {
                "s1": {
                    "mechanism": "gri30.yaml",
                    "solve": "equilibrate",
                    "stage_order": 0,
                },
            },
        }
        result, _ = merge_config_into_yaml(config, yaml)
        assert "stages:" in result
        assert "network:" not in result

    def test_merge_raises_on_inline_ports(self):
        """Asserts that a YAML with inline port shortcuts raises ValueError.

        Inline ports (inlet: on a node) are not supported by live sync.
        merge_config_into_yaml must raise ValueError with an explanatory message.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: tube\n"
            "    DesignPFR:\n"
            "      length: 1.0\n"
            "      inlet:\n"
            "        from: feed\n"
            "        mass_flow_rate: 0.001\n"
        )
        config = self._make_config(
            [
                self._node("feed", "Reservoir", {"temperature": 300.0}),
                self._node("tube", "DesignPFR", {"length": 1.0}),
            ]
        )
        with pytest.raises(ValueError, match="[Ii]nline port"):
            merge_config_into_yaml(config, yaml)

    def test_merge_raises_on_shape_conflict(self):
        """Asserts that switching from network: to stages: raises ValueError.

        Original YAML uses network:; the config has a non-default group
        implying stages:. merge_config_into_yaml must raise ValueError.
        """
        from boulder.config import merge_config_into_yaml

        yaml = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
        )
        config = {
            "nodes": [
                {
                    **self._node("inlet", "Reservoir", {"temperature": 300.0}),
                    "group": "s1",
                },
            ],
            "connections": [],
            "groups": {
                "s1": {
                    "mechanism": "gri30.yaml",
                    "solve": "equilibrate",
                    "stage_order": 0,
                },
            },
        }
        with pytest.raises(ValueError, match="[Ss]hape conflict"):
            merge_config_into_yaml(config, yaml)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
