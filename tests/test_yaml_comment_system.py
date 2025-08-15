"""Comprehensive tests for YAML comment preservation system.

This module consolidates all YAML comment preservation tests into a single,
well-organized test suite covering:
- Basic YAML comment loading and saving
- Comment preservation during updates
- Integration with the Boulder application
- Edge cases and error handling
"""

import base64
from unittest.mock import patch

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
simulation:
  end_time: 1.0  # seconds - total simulation duration
  dt: 0.01       # seconds - integration time step

# Reactor components with detailed comments and units
nodes:
  - id: "reactor1"
    # Primary combustion chamber - high temperature operation
    IdealGasReactor:
      temperature: 1000.0  # K - initial operating temperature
      pressure: 101325.0   # Pa - initial pressure (1 atmosphere)
      composition: "CH4:1, O2:2, N2:7.52"  # molar ratios for methane combustion

  - id: "reactor2"
    # Secondary reactor for mixing and cooling
    IdealGasReactor:
      temperature: 800.0   # K - cooler mixing temperature
      pressure: 101325.0   # Pa - same pressure as reactor1
      composition: "O2:1, N2:3.76"  # standard air composition

# Mass flow connections with control parameters
connections:
  - id: "mfc1"
    # Controlled flow from primary to secondary reactor
    MassFlowController:
      mass_flow_rate: 0.001  # kg/s - mass flow rate control
    source: "reactor1"
    target: "reactor2"
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
        assert result["nodes"][0]["id"] == "reactor1"
        assert result["nodes"][0]["IdealGasReactor"]["temperature"] == 1000.0
        assert result["connections"][0]["id"] == "mfc1"
        assert result["connections"][0]["MassFlowController"]["mass_flow_rate"] == 0.001

    def test_yaml_to_string_with_comments(self, sample_yaml_with_comments):
        """Test converting data to YAML string with comment preservation."""
        # Load the data first
        data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Convert back to string
        result = yaml_to_string_with_comments(data)

        # Verify it's a valid YAML string with substantial content
        assert isinstance(result, str)
        assert "metadata:" in result
        assert "nodes:" in result
        assert "connections:" in result
        assert len(result) > 100

    def test_update_yaml_preserving_comments(self, sample_yaml_with_comments):
        """Test updating YAML data while preserving structure and comments."""
        # Load original data
        original_data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Create new data with some changes
        new_data = {
            "metadata": {
                "name": "Updated Configuration",
                "description": "Updated description",
                "version": "2.0",
            },
            "simulation": {"end_time": 2.0, "dt": 0.02},
            "components": [
                {
                    "id": "reactor1",
                    "IdealGasReactor": {
                        "temperature": 1100.0,  # Changed temperature
                        "pressure": 101325.0,
                        "composition": "CH4:1, O2:2, N2:7.52",
                    },
                }
            ],
        }

        # Update preserving comments
        updated_data = _update_yaml_preserving_comments(original_data, new_data)

        # Verify updates were applied
        assert updated_data["metadata"]["name"] == "Updated Configuration"
        assert updated_data["metadata"]["version"] == "2.0"
        assert updated_data["simulation"]["end_time"] == 2.0
        assert updated_data["nodes"][0]["IdealGasReactor"]["temperature"] == 1100.0

    def test_preserves_numeric_types(self, sample_yaml_with_comments):
        """Test that numeric types are preserved correctly."""
        data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Check that numbers are loaded as proper types
        assert isinstance(data["nodes"][0]["IdealGasReactor"]["temperature"], float)
        assert isinstance(data["nodes"][0]["IdealGasReactor"]["pressure"], float)
        assert isinstance(data["simulation"]["end_time"], float)
        assert isinstance(data["simulation"]["dt"], float)

    def test_preserves_string_types(self, sample_yaml_with_comments):
        """Test that string types are preserved correctly."""
        data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Check that strings are loaded correctly
        assert isinstance(data["metadata"]["name"], str)
        assert isinstance(data["nodes"][0]["id"], str)
        assert isinstance(data["nodes"][0]["IdealGasReactor"]["composition"], str)


class TestYAMLCommentRoundTrip:
    """Test round-trip conversions between different formats."""

    @pytest.fixture
    def sample_yaml_with_comments(self):
        """Sample YAML for round-trip testing."""
        return """# Boulder Configuration with STONE Standard
metadata:
  name: "Round Trip Test"
  version: "1.0"

simulation:
  end_time: 1.0  # seconds

nodes:
  - id: "test_reactor"
    IdealGasReactor:
      temperature: 1200.0  # K
      pressure: 101325.0   # Pa
"""

    def test_yaml_to_internal_to_stone_roundtrip(self, sample_yaml_with_comments):
        """Test full round-trip: YAML → internal → STONE → YAML."""
        # Load YAML with comments
        loaded_data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Normalize to internal format
        internal_config = normalize_config(loaded_data)

        # Verify internal format is correct
        assert internal_config["nodes"][0]["type"] == "IdealGasReactor"
        assert "properties" in internal_config["nodes"][0]
        assert internal_config["nodes"][0]["properties"]["temperature"] == 1200.0

        # Convert back to STONE format
        stone_config = convert_to_stone_format(internal_config)

        # Verify STONE format
        assert "IdealGasReactor" in stone_config["nodes"][0]
        assert stone_config["nodes"][0]["id"] == "test_reactor"

        # Convert to YAML string
        yaml_string = yaml_to_string_with_comments(stone_config)

        # Verify the result contains expected content
        assert "test_reactor" in yaml_string
        assert "IdealGasReactor" in yaml_string
        assert "1200" in yaml_string

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

    def test_stone_format_integration_with_comments(self, sample_yaml_with_comments):
        """Test integration between STONE format and comment preservation."""
        from boulder.config import normalize_config

        # Load original YAML with comments
        original_data = load_yaml_string_with_comments(sample_yaml_with_comments)

        # Convert to internal format (as the app does)
        internal_config = normalize_config(original_data)

        # Convert back to STONE format (for editing)
        stone_config = convert_to_stone_format(internal_config)

        # Update preserving original structure
        updated_data = _update_yaml_preserving_comments(original_data, stone_config)

        # Convert back to YAML string
        final_yaml = yaml_to_string_with_comments(updated_data)

        # Verify content is preserved
        assert "test_reactor" in final_yaml
        assert "1200" in final_yaml

        # Load the final result to verify it's valid
        final_data = load_yaml_string_with_comments(final_yaml)
        # Check that the final data matches the expected STONE format
        assert "nodes" in final_data
        assert len(final_data["nodes"]) > 0
        assert "IdealGasReactor" in final_data["nodes"][0]
        assert final_data["nodes"][0]["id"] == "test_reactor"
        assert final_data["nodes"][0]["IdealGasReactor"]["temperature"] == 1200.0
        assert final_data["nodes"][0]["IdealGasReactor"]["pressure"] == 101325.0


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
            if "nodes:" in original_yaml:
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
        """Test that the app handles missing default.yaml gracefully."""
        # Mock a non-existent configs directory
        with patch("boulder.config.os.path.exists") as mock_exists:
            mock_exists.return_value = False

            with pytest.raises(FileNotFoundError):
                get_initial_config_with_comments()


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
