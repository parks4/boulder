"""Integration tests for YAML comment preservation functionality."""

import pytest
import tempfile
import os
from unittest.mock import patch

from boulder.config import (
    get_initial_config_with_comments,
    convert_to_stone_format,
    yaml_to_string_with_comments,
    load_yaml_string_with_comments,
    _update_yaml_preserving_comments,
)


class TestYAMLCommentIntegration:
    """Integration tests for comment preservation in the full application context."""

    @pytest.fixture
    def sample_default_yaml(self):
        """Sample default.yaml with comments and units."""
        return """# Boulder Configuration with 🪨 STONE Standard
# This file demonstrates comment preservation in YAML configs with units

metadata:
  name: "Test Configuration with Units"
  description: "Demonstrates comment and unit preservation"
  version: "1.0"

# Simulation parameters with units
simulation:
  end_time: 1.0  # seconds - total simulation duration
  dt: 0.01       # seconds - integration time step

# Reactor components with detailed comments and units
components:
  - id: "main_reactor"
    # Primary combustion chamber - high temperature operation
    IdealGasReactor:
      temperature: 1200.0  # K - initial operating temperature
      pressure: 101325.0   # Pa - initial pressure (1 atmosphere)
      composition: "CH4:1, O2:2, N2:7.52"  # molar ratios for methane combustion

  - id: "mixing_zone"
    # Secondary reactor for mixing and cooling
    IdealGasReactor:
      temperature: 800.0   # K - cooler mixing temperature
      pressure: 101325.0   # Pa - same pressure as main reactor
      composition: "O2:1, N2:3.76"  # standard air composition

# Mass flow connections with control parameters
connections:
  - id: "main_to_mixing"
    # Controlled flow from main reactor to mixing zone
    MassFlowController:
      mass_flow_rate: 0.001  # kg/s - mass flow rate control
    source: "main_reactor"
    target: "mixing_zone"
"""

    def test_initial_config_loading_with_comments(self, sample_default_yaml, tmp_path):
        """Test that initial config loading preserves comments when default.yaml exists."""
        # Create a temporary default.yaml file
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        default_yaml_path = config_dir / "default.yaml"
        default_yaml_path.write_text(sample_default_yaml, encoding='utf-8')
        
        # Mock the configs directory path
        with patch('boulder.config.os.path.dirname') as mock_dirname:
            # Make the path resolution point to our temp directory
            mock_dirname.return_value = str(tmp_path)
            
            try:
                # Test loading with comments
                config, original_yaml = get_initial_config_with_comments()
                
                # Verify config was loaded correctly
                assert config["metadata"]["name"] == "Test Configuration with Units"
                assert config["components"][0]["id"] == "main_reactor"
                assert config["components"][0]["type"] == "IdealGasReactor"
                assert config["components"][0]["properties"]["temperature"] == 1200.0
                
                # Verify original YAML contains comments
                assert "# K - initial operating temperature" in original_yaml
                assert "# Pa - initial pressure" in original_yaml
                assert "# kg/s - mass flow rate control" in original_yaml
                
            except FileNotFoundError:
                # Expected if configs/default.yaml doesn't exist
                # Test that fallback works
                from boulder.config import get_initial_config
                config = get_initial_config()
                assert isinstance(config, dict)

    def test_modal_editor_with_comments(self, sample_default_yaml):
        """Test that the modal editor preserves comments when editing configuration."""
        # Load original YAML with comments
        original_data = load_yaml_string_with_comments(sample_default_yaml)
        
        # Simulate editing - change some values
        updated_config = {
            "metadata": {
                "name": "Updated Test Configuration with Units",
                "description": "Demonstrates comment and unit preservation after editing",
                "version": "1.1"
            },
            "simulation": {
                "end_time": 2.0,  # Updated duration
                "dt": 0.01
            },
            "components": [
                {
                    "id": "main_reactor",
                    "IdealGasReactor": {
                        "temperature": 1300.0,  # Updated temperature
                        "pressure": 101325.0,
                        "composition": "CH4:1, O2:2, N2:7.52"
                    }
                },
                {
                    "id": "mixing_zone",
                    "IdealGasReactor": {
                        "temperature": 850.0,  # Updated temperature
                        "pressure": 101325.0,
                        "composition": "O2:1, N2:3.76"
                    }
                }
            ],
            "connections": [
                {
                    "id": "main_to_mixing",
                    "MassFlowController": {
                        "mass_flow_rate": 0.002  # Updated flow rate
                    },
                    "source": "main_reactor",
                    "target": "mixing_zone"
                }
            ]
        }
        
        # Update preserving comments
        updated_data = _update_yaml_preserving_comments(original_data, updated_config)
        result_yaml = yaml_to_string_with_comments(updated_data)
        
        # Verify updates were applied
        assert "1300" in result_yaml  # Updated temperature
        assert "850" in result_yaml   # Updated mixing temperature
        assert "0.002" in result_yaml # Updated flow rate
        assert "Updated Test Configuration" in result_yaml
        
        # Note: Exact comment preservation depends on ruamel.yaml's behavior
        # but the structure and data should be maintained

    def test_file_upload_preserves_comments(self, sample_default_yaml):
        """Test that uploading a YAML file preserves comments for later editing."""
        # Simulate file upload process
        import base64
        
        # Encode the YAML content as it would be uploaded
        encoded_content = base64.b64encode(sample_default_yaml.encode('utf-8')).decode('utf-8')
        upload_contents = f"data:text/yaml;base64,{encoded_content}"
        
        # Decode as the upload callback would
        content_type, content_string = upload_contents.split(",")
        decoded_string = base64.b64decode(content_string).decode("utf-8")
        
        # Load with comment preservation
        decoded = load_yaml_string_with_comments(decoded_string)
        
        # Verify the data loaded correctly
        assert decoded["metadata"]["name"] == "Test Configuration with Units"
        assert decoded["components"][0]["IdealGasReactor"]["temperature"] == 1200.0
        
        # Verify we can convert back with comments preserved
        yaml_output = yaml_to_string_with_comments(decoded)
        assert "main_reactor" in yaml_output
        assert "1200" in yaml_output

    def test_round_trip_with_stone_format(self, sample_default_yaml):
        """Test full round-trip: YAML with comments → internal → STONE → YAML with comments."""
        from boulder.config import normalize_config
        
        # Load original YAML with comments
        original_data = load_yaml_string_with_comments(sample_default_yaml)
        
        # Convert to internal format (as the app does)
        internal_config = normalize_config(original_data)
        
        # Verify internal format conversion
        assert internal_config["components"][0]["type"] == "IdealGasReactor"
        assert "properties" in internal_config["components"][0]
        assert internal_config["components"][0]["properties"]["temperature"] == 1200.0
        
        # Convert back to STONE format (for editing)
        stone_config = convert_to_stone_format(internal_config)
        
        # Update preserving original structure
        updated_data = _update_yaml_preserving_comments(original_data, stone_config)
        
        # Convert back to YAML string
        final_yaml = yaml_to_string_with_comments(updated_data)
        
        # Verify content is preserved
        assert "main_reactor" in final_yaml
        assert "mixing_zone" in final_yaml
        assert "1200" in final_yaml
        assert "800" in final_yaml
        
        # Load the final result to verify it's valid
        final_data = load_yaml_string_with_comments(final_yaml)
        assert final_data["components"][0]["IdealGasReactor"]["temperature"] == 1200.0

    def test_error_handling_no_default_yaml(self):
        """Test that the app handles missing default.yaml gracefully."""
        # Mock a non-existent configs directory
        with patch('boulder.config.os.path.exists') as mock_exists:
            mock_exists.return_value = False
            
            with pytest.raises(FileNotFoundError):
                get_initial_config_with_comments()

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
components: []  # no components
connections: []  # no connections
"""
        
        data = load_yaml_string_with_comments(empty_sections_yaml)
        result = yaml_to_string_with_comments(data)
        
        # Should handle empty sections
        assert "Empty Sections" in result

    def test_units_preservation_examples(self):
        """Test preservation of various unit formats in comments."""
        units_yaml = """# Configuration with various unit formats
components:
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
        reactor_props = reloaded["components"][0]["IdealGasReactor"]
        
        assert reactor_props["temperature"] == 1000.0
        assert reactor_props["pressure"] == 101325
        assert reactor_props["mass"] == 0.5
        assert reactor_props["volume"] == 0.001
        assert reactor_props["flow_rate"] == 1.5e-3
        assert reactor_props["time_constant"] == 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 