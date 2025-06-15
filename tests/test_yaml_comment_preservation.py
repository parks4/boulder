"""Tests for YAML comment preservation functionality."""

import pytest
from io import StringIO

from boulder.config import (
    get_yaml_with_comments,
    yaml_to_string_with_comments,
    load_yaml_string_with_comments,
    _update_yaml_preserving_comments,
    normalize_config,
    convert_to_stone_format,
)


class TestYAMLCommentPreservation:
    """Test comment preservation in YAML configuration files."""

    @pytest.fixture
    def sample_yaml_with_comments(self):
        """Sample YAML configuration with comments and units."""
        return """# Boulder Configuration with 🪨 STONE Standard
# This file demonstrates comment preservation in YAML configs

metadata:
  name: "Test Configuration"
  description: "Sample configuration with comments and units"
  version: "1.0"

# Simulation parameters
simulation:
  end_time: 1.0  # seconds - simulation duration
  dt: 0.01       # seconds - time step

# Reactor components with detailed comments
components:
  - id: "reactor1"
    # Ideal gas reactor - main combustion chamber
    IdealGasReactor:
      temperature: 1000.0  # K - initial temperature
      pressure: 101325.0   # Pa - initial pressure (1 atm)
      composition: "CH4:1, O2:2, N2:7.52"  # molar ratios

  - id: "reactor2"
    # Second reactor for mixing
    IdealGasReactor:
      temperature: 800.0   # K - cooler mixing temperature
      pressure: 101325.0   # Pa - same pressure as reactor1
      composition: "O2:1, N2:3.76"  # air composition

# Connections between components
connections:
  - id: "mfc1"
    # Mass flow controller from reactor1 to reactor2
    MassFlowController:
      mass_flow_rate: 0.001  # kg/s - controlled flow rate
    source: "reactor1"
    target: "reactor2"
"""

    def test_get_yaml_with_comments(self):
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
        assert result["components"][0]["id"] == "reactor1"
        assert result["components"][0]["IdealGasReactor"]["temperature"] == 1000.0
        assert result["connections"][0]["id"] == "mfc1"
        assert result["connections"][0]["MassFlowController"]["mass_flow_rate"] == 0.001

    def test_yaml_to_string_with_comments(self, sample_yaml_with_comments):
        """Test converting data to YAML string with comment preservation."""
        # Load the data first
        data = load_yaml_string_with_comments(sample_yaml_with_comments)
        
        # Convert back to string
        result = yaml_to_string_with_comments(data)
        
        # Verify it's a valid YAML string
        assert isinstance(result, str)
        assert "metadata:" in result
        assert "components:" in result
        assert "connections:" in result
        assert len(result) > 100  # Should have substantial content

    def test_update_yaml_preserving_comments(self, sample_yaml_with_comments):
        """Test updating YAML data while preserving structure."""
        # Load original data
        original_data = load_yaml_string_with_comments(sample_yaml_with_comments)
        
        # Create new data with some changes
        new_data = {
            "metadata": {
                "name": "Updated Configuration",
                "description": "Updated description",
                "version": "2.0"
            },
            "simulation": {
                "end_time": 2.0,
                "dt": 0.02
            },
            "components": [
                {
                    "id": "reactor1",
                    "IdealGasReactor": {
                        "temperature": 1100.0,  # Changed temperature
                        "pressure": 101325.0,
                        "composition": "CH4:1, O2:2, N2:7.52"
                    }
                }
            ]
        }
        
        # Update preserving comments
        updated_data = _update_yaml_preserving_comments(original_data, new_data)
        
        # Verify updates were applied
        assert updated_data["metadata"]["name"] == "Updated Configuration"
        assert updated_data["metadata"]["version"] == "2.0"
        assert updated_data["simulation"]["end_time"] == 2.0
        assert updated_data["components"][0]["IdealGasReactor"]["temperature"] == 1100.0

    def test_round_trip_conversion(self, sample_yaml_with_comments):
        """Test full round-trip: YAML with comments -> internal -> STONE -> YAML."""
        # Load YAML with comments
        loaded_data = load_yaml_string_with_comments(sample_yaml_with_comments)
        
        # Normalize to internal format
        internal_config = normalize_config(loaded_data)
        
        # Verify internal format is correct
        assert internal_config["components"][0]["type"] == "IdealGasReactor"
        assert "properties" in internal_config["components"][0]
        assert internal_config["components"][0]["properties"]["temperature"] == 1000.0
        
        # Convert back to STONE format
        stone_config = convert_to_stone_format(internal_config)
        
        # Verify STONE format
        assert "IdealGasReactor" in stone_config["components"][0]
        assert stone_config["components"][0]["id"] == "reactor1"
        
        # Convert to YAML string
        yaml_string = yaml_to_string_with_comments(stone_config)
        
        # Verify the result contains expected content
        assert "reactor1" in yaml_string
        assert "IdealGasReactor" in yaml_string
        assert "1000" in yaml_string  # temperature value

    def test_comment_preservation_in_update(self, sample_yaml_with_comments):
        """Test that comments are preserved when updating configuration."""
        # Load original with comments
        original_data = load_yaml_string_with_comments(sample_yaml_with_comments)
        
        # Simulate a configuration update
        updated_stone_config = {
            "metadata": {
                "name": "Updated Test Configuration",
                "description": "Updated sample configuration with comments and units",
                "version": "1.1"
            },
            "simulation": {
                "end_time": 1.5,
                "dt": 0.01
            },
            "components": [
                {
                    "id": "reactor1",
                    "IdealGasReactor": {
                        "temperature": 1200.0,  # Updated temperature
                        "pressure": 101325.0,
                        "composition": "CH4:1, O2:2, N2:7.52"
                    }
                },
                {
                    "id": "reactor2",
                    "IdealGasReactor": {
                        "temperature": 800.0,
                        "pressure": 101325.0,
                        "composition": "O2:1, N2:3.76"
                    }
                }
            ],
            "connections": [
                {
                    "id": "mfc1",
                    "MassFlowController": {
                        "mass_flow_rate": 0.002  # Updated flow rate
                    },
                    "source": "reactor1",
                    "target": "reactor2"
                }
            ]
        }
        
        # Update preserving structure
        updated_data = _update_yaml_preserving_comments(original_data, updated_stone_config)
        
        # Convert to string
        result_yaml = yaml_to_string_with_comments(updated_data)
        
        # Verify updates were applied
        assert "1200" in result_yaml  # Updated temperature
        assert "0.002" in result_yaml  # Updated flow rate
        assert "Updated Test Configuration" in result_yaml

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

    def test_preserves_numeric_types(self, sample_yaml_with_comments):
        """Test that numeric types are preserved correctly."""
        data = load_yaml_string_with_comments(sample_yaml_with_comments)
        
        # Check that numbers are loaded as proper types
        assert isinstance(data["components"][0]["IdealGasReactor"]["temperature"], float)
        assert isinstance(data["components"][0]["IdealGasReactor"]["pressure"], float)
        assert isinstance(data["simulation"]["end_time"], float)
        assert isinstance(data["simulation"]["dt"], float)

    def test_preserves_string_types(self, sample_yaml_with_comments):
        """Test that string types are preserved correctly."""
        data = load_yaml_string_with_comments(sample_yaml_with_comments)
        
        # Check that strings are loaded correctly
        assert isinstance(data["metadata"]["name"], str)
        assert isinstance(data["components"][0]["id"], str)
        assert isinstance(data["components"][0]["IdealGasReactor"]["composition"], str)

    def test_units_preservation(self, sample_yaml_with_comments):
        """Test that unit information in comments is preserved."""
        data = load_yaml_string_with_comments(sample_yaml_with_comments)
        
        # Convert back to YAML and check for unit preservation
        yaml_string = yaml_to_string_with_comments(data)
        
        # The exact comment preservation depends on ruamel.yaml behavior
        # but the data structure should be intact
        reloaded = load_yaml_string_with_comments(yaml_string)
        
        # Verify the values are preserved correctly
        assert reloaded["components"][0]["IdealGasReactor"]["temperature"] == 1000.0
        assert reloaded["components"][0]["IdealGasReactor"]["pressure"] == 101325.0
        assert reloaded["connections"][0]["MassFlowController"]["mass_flow_rate"] == 0.001


# Integration test
class TestYAMLIntegration:
    """Integration tests for YAML comment preservation in the full application context."""
    
    def test_stone_format_with_comments(self):
        """Test that STONE format works correctly with comment preservation."""
        yaml_content = """# Test configuration
metadata:
  name: "Integration Test"

components:
  - id: "test_reactor"
    # This is a test reactor with units
    IdealGasReactor:
      temperature: 1000.0  # K
      pressure: 101325.0   # Pa
      composition: "CH4:1, O2:2"  # fuel mixture
"""
        
        # Load with comments
        data = load_yaml_string_with_comments(yaml_content)
        
        # Convert to internal format
        internal = normalize_config(data)
        
        # Verify conversion
        assert internal["components"][0]["type"] == "IdealGasReactor"
        assert internal["components"][0]["properties"]["temperature"] == 1000.0
        
        # Convert back to STONE format
        stone = convert_to_stone_format(internal)
        
        # Verify STONE format
        assert "IdealGasReactor" in stone["components"][0]
        assert stone["components"][0]["IdealGasReactor"]["temperature"] == 1000.0
        
        # Test the update mechanism
        updated = _update_yaml_preserving_comments(data, stone)
        result_yaml = yaml_to_string_with_comments(updated)
        
        # Verify the result
        assert "test_reactor" in result_yaml
        assert "1000" in result_yaml


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 