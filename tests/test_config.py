#!/usr/bin/env python3
"""
Comprehensive unit tests for Boulder configuration system.
Tests focus on validation, error handling, and edge cases.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, mock_open
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from boulder.config import (
    ConfigurationError,
    load_config_file,
    validate_config_structure,
    validate_component_references,
    normalize_config,
    get_component_by_id,
    get_connections_for_component,
    save_config_to_file,
    get_initial_config,
    get_config_from_path
)


class TestConfigurationValidation(unittest.TestCase):
    """Test configuration validation and error handling."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.valid_config = {
            "metadata": {
                "name": "Test Configuration",
                "version": "1.0"
            },
            "simulation": {
                "mechanism": "gri30.yaml",
                "time_step": 0.001,
                "max_time": 10.0
            },
            "components": [
                {
                    "id": "reactor1",
                    "type": "IdealGasReactor",
                    "temperature": 1000,
                    "pressure": 101325,
                    "composition": "CH4:1,O2:2,N2:7.52"
                },
                {
                    "id": "res1",
                    "type": "Reservoir",
                    "temperature": 300,
                    "composition": "O2:1,N2:3.76"
                }
            ],
            "connections": [
                {
                    "id": "mfc1",
                    "type": "MassFlowController",
                    "source": "res1",
                    "target": "reactor1",
                    "mass_flow_rate": 0.1
                }
            ]
        }
    
    def test_missing_components_section(self):
        """Test error when components section is missing."""
        config = self.valid_config.copy()
        del config['components']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Missing required section: 'components'", str(cm.exception))
    
    def test_missing_connections_section(self):
        """Test error when connections section is missing."""
        config = self.valid_config.copy()
        del config['connections']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Missing required section: 'connections'", str(cm.exception))
    
    def test_components_not_list(self):
        """Test error when components is not a list."""
        config = self.valid_config.copy()
        config['components'] = {"not": "a list"}
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("'components' must be a list", str(cm.exception))
    
    def test_connections_not_list(self):
        """Test error when connections is not a list."""
        config = self.valid_config.copy()
        config['connections'] = {"not": "a list"}
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("'connections' must be a list", str(cm.exception))
    
    def test_component_not_dict(self):
        """Test error when component is not a dictionary."""
        config = self.valid_config.copy()
        config['components'][0] = "not a dict"
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Component 0 must be a dictionary", str(cm.exception))
    
    def test_connection_not_dict(self):
        """Test error when connection is not a dictionary."""
        config = self.valid_config.copy()
        config['connections'][0] = "not a dict"
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Connection 0 must be a dictionary", str(cm.exception))
    
    def test_component_missing_id(self):
        """Test error when component is missing ID field."""
        config = self.valid_config.copy()
        del config['components'][0]['id']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Component 0 missing required field: 'id'", str(cm.exception))
    
    def test_component_missing_type(self):
        """Test error when component is missing type field."""
        config = self.valid_config.copy()
        del config['components'][0]['type']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Component 0 missing required field: 'type'", str(cm.exception))
    
    def test_connection_missing_id(self):
        """Test error when connection is missing ID field."""
        config = self.valid_config.copy()
        del config['connections'][0]['id']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Connection 0 missing required field: 'id'", str(cm.exception))
    
    def test_connection_missing_type(self):
        """Test error when connection is missing type field."""
        config = self.valid_config.copy()
        del config['connections'][0]['type']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Connection 0 missing required field: 'type'", str(cm.exception))
    
    def test_connection_missing_source(self):
        """Test error when connection is missing source field."""
        config = self.valid_config.copy()
        del config['connections'][0]['source']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Connection 0 missing required field: 'source'", str(cm.exception))
    
    def test_connection_missing_target(self):
        """Test error when connection is missing target field."""
        config = self.valid_config.copy()
        del config['connections'][0]['target']
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("Connection 0 missing required field: 'target'", str(cm.exception))
    
    def test_metadata_not_dict(self):
        """Test error when metadata is not a dictionary."""
        config = self.valid_config.copy()
        config['metadata'] = "not a dict"
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("'metadata' must be a dictionary", str(cm.exception))
    
    def test_simulation_not_dict(self):
        """Test error when simulation is not a dictionary."""
        config = self.valid_config.copy()
        config['simulation'] = "not a dict"
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_config_structure(config)
        
        self.assertIn("'simulation' must be a dictionary", str(cm.exception))
    
    def test_invalid_component_reference_source(self):
        """Test error when connection references non-existent source component."""
        config = self.valid_config.copy()
        config['connections'][0]['source'] = 'nonexistent_component'
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_component_references(config)
        
        self.assertIn("references unknown source component: 'nonexistent_component'", str(cm.exception))
    
    def test_invalid_component_reference_target(self):
        """Test error when connection references non-existent target component."""
        config = self.valid_config.copy()
        config['connections'][0]['target'] = 'nonexistent_component'
        
        with self.assertRaises(ConfigurationError) as cm:
            validate_component_references(config)
        
        self.assertIn("references unknown target component: 'nonexistent_component'", str(cm.exception))
    
    def test_valid_config_passes_validation(self):
        """Test that a valid configuration passes all validation."""
        # Should not raise any exceptions
        validate_config_structure(self.valid_config)
        validate_component_references(self.valid_config)
    
    def test_empty_components_list(self):
        """Test handling of empty components list."""
        config = self.valid_config.copy()
        config['components'] = []
        config['connections'] = []  # Empty connections to match
        
        # Structure validation should pass
        validate_config_structure(config)
        validate_component_references(config)
    
    def test_empty_connections_list(self):
        """Test handling of empty connections list."""
        config = self.valid_config.copy()
        config['connections'] = []
        
        # Should pass validation
        validate_config_structure(config)
        validate_component_references(config)


class TestConfigurationLoading(unittest.TestCase):
    """Test configuration file loading and parsing."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.valid_yaml_content = """
metadata:
  name: "Test Configuration"
  version: "1.0"

simulation:
  mechanism: "gri30.yaml"
  time_step: 0.001
  max_time: 10.0

components:
  - id: reactor1
    type: IdealGasReactor
    temperature: 1000
    pressure: 101325
    composition: "CH4:1,O2:2,N2:7.52"
    
  - id: res1
    type: Reservoir
    temperature: 300
    composition: "O2:1,N2:3.76"

connections:
  - id: mfc1
    type: MassFlowController
    source: res1
    target: reactor1
    mass_flow_rate: 0.1
"""
        
        self.valid_json_content = json.dumps({
            "metadata": {"name": "Test Configuration", "version": "1.0"},
            "simulation": {"mechanism": "gri30.yaml", "time_step": 0.001, "max_time": 10.0},
            "components": [
                {"id": "reactor1", "type": "IdealGasReactor", "temperature": 1000, "pressure": 101325, "composition": "CH4:1,O2:2,N2:7.52"},
                {"id": "res1", "type": "Reservoir", "temperature": 300, "composition": "O2:1,N2:3.76"}
            ],
            "connections": [
                {"id": "mfc1", "type": "MassFlowController", "source": "res1", "target": "reactor1", "mass_flow_rate": 0.1}
            ]
        })
    
    def test_file_not_found(self):
        """Test error when configuration file doesn't exist."""
        with self.assertRaises(FileNotFoundError) as cm:
            load_config_file("nonexistent_file.yaml")
        
        self.assertIn("Configuration file not found", str(cm.exception))
    
    def test_invalid_yaml_syntax(self):
        """Test error with invalid YAML syntax."""
        invalid_yaml = """
        metadata:
          name: "Test Configuration"
          version: 1.0
        invalid_yaml: [unclosed bracket
        """
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(invalid_yaml)
            f.flush()
            
            try:
                with self.assertRaises(ConfigurationError) as cm:
                    load_config_file(f.name)
                
                self.assertIn("YAML parsing error", str(cm.exception))
            finally:
                os.unlink(f.name)
    
    def test_invalid_json_syntax(self):
        """Test error with invalid JSON syntax."""
        invalid_json = '{"metadata": {"name": "Test"}, "invalid": json}'
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(invalid_json)
            f.flush()
            
            try:
                with self.assertRaises(ConfigurationError) as cm:
                    load_config_file(f.name)
                
                self.assertIn("JSON parsing error", str(cm.exception))
            finally:
                os.unlink(f.name)
    
    def test_yaml_without_pyyaml(self):
        """Test error when trying to load YAML without PyYAML installed."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.valid_yaml_content)
            f.flush()
            
            try:
                with patch('boulder.config.YAML_AVAILABLE', False):
                    with self.assertRaises(ImportError) as cm:
                        load_config_file(f.name)
                    
                    self.assertIn("PyYAML is required", str(cm.exception))
            finally:
                os.unlink(f.name)
    
    def test_valid_yaml_loading(self):
        """Test successful loading of valid YAML configuration."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.valid_yaml_content)
            f.flush()
            
            try:
                config = load_config_file(f.name)
                self.assertIsInstance(config, dict)
                self.assertEqual(config['metadata']['name'], "Test Configuration")
                self.assertEqual(len(config['components']), 2)
                self.assertEqual(len(config['connections']), 1)
            finally:
                os.unlink(f.name)
    
    def test_valid_json_loading(self):
        """Test successful loading of valid JSON configuration."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(self.valid_json_content)
            f.flush()
            
            try:
                config = load_config_file(f.name)
                self.assertIsInstance(config, dict)
                self.assertEqual(config['metadata']['name'], "Test Configuration")
                self.assertEqual(len(config['components']), 2)
                self.assertEqual(len(config['connections']), 1)
            finally:
                os.unlink(f.name)
    
    def test_malformed_config_structure(self):
        """Test error with malformed configuration structure."""
        malformed_yaml = """
        components:
          - id: reactor1
            # Missing type field
            temperature: 1000
        connections: []
        """
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(malformed_yaml)
            f.flush()
            
            try:
                with self.assertRaises(ConfigurationError) as cm:
                    load_config_file(f.name)
                
                self.assertIn("missing required field: 'type'", str(cm.exception))
            finally:
                os.unlink(f.name)


class TestConfigurationNormalization(unittest.TestCase):
    """Test configuration normalization functionality."""
    
    def test_add_default_simulation_params(self):
        """Test adding default simulation parameters."""
        config = {
            "components": [{"id": "test", "type": "Reactor"}],
            "connections": []
        }
        
        normalized = normalize_config(config)
        
        self.assertIn('simulation', normalized)
        self.assertIn('mechanism', normalized['simulation'])
        self.assertEqual(normalized['simulation']['mechanism'], 'gri30.yaml')
    
    def test_merge_simulation_params(self):
        """Test merging with existing simulation parameters."""
        config = {
            "simulation": {"time_step": 0.01},
            "components": [{"id": "test", "type": "Reactor"}],
            "connections": []
        }
        
        normalized = normalize_config(config)
        
        # Should keep custom time_step but add defaults
        self.assertEqual(normalized['simulation']['time_step'], 0.01)
        self.assertEqual(normalized['simulation']['mechanism'], 'gri30.yaml')
    
    def test_add_default_metadata(self):
        """Test adding default metadata."""
        config = {
            "components": [{"id": "test", "type": "Reactor"}],
            "connections": []
        }
        
        normalized = normalize_config(config)
        
        self.assertIn('metadata', normalized)
        self.assertEqual(normalized['metadata']['name'], 'Unnamed Configuration')
    
    def test_normalize_component_properties(self):
        """Test normalization of component properties."""
        config = {
            "components": [
                {
                    "id": "reactor1",
                    "type": "IdealGasReactor",
                    "temperature": 1000,
                    "pressure": 101325
                }
            ],
            "connections": []
        }
        
        normalized = normalize_config(config)
        
        # Properties should be moved to properties dict
        component = normalized['components'][0]
        self.assertIn('properties', component)
        self.assertEqual(component['properties']['temperature'], 1000)
        self.assertEqual(component['properties']['pressure'], 101325)
    
    def test_normalize_connection_properties(self):
        """Test normalization of connection properties."""
        config = {
            "components": [
                {"id": "res1", "type": "Reservoir"},
                {"id": "reactor1", "type": "Reactor"}
            ],
            "connections": [
                {
                    "id": "mfc1",
                    "type": "MassFlowController",
                    "source": "res1",
                    "target": "reactor1",
                    "mass_flow_rate": 0.1
                }
            ]
        }
        
        normalized = normalize_config(config)
        
        # Properties should be moved to properties dict
        connection = normalized['connections'][0]
        self.assertIn('properties', connection)
        self.assertEqual(connection['properties']['mass_flow_rate'], 0.1)


class TestConfigurationUtilities(unittest.TestCase):
    """Test configuration utility functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "components": [
                {"id": "reactor1", "type": "IdealGasReactor"},
                {"id": "res1", "type": "Reservoir"},
                {"id": "res2", "type": "Reservoir"}
            ],
            "connections": [
                {"id": "mfc1", "type": "MassFlowController", "source": "res1", "target": "reactor1"},
                {"id": "mfc2", "type": "MassFlowController", "source": "reactor1", "target": "res2"},
                {"id": "valve1", "type": "Valve", "source": "res1", "target": "res2"}
            ]
        }
    
    def test_get_component_by_id_found(self):
        """Test finding a component by ID."""
        component = get_component_by_id(self.config, "reactor1")
        self.assertIsNotNone(component)
        self.assertEqual(component['id'], "reactor1")
        self.assertEqual(component['type'], "IdealGasReactor")
    
    def test_get_component_by_id_not_found(self):
        """Test component not found by ID."""
        component = get_component_by_id(self.config, "nonexistent")
        self.assertIsNone(component)
    
    def test_get_connections_for_component(self):
        """Test getting connections for a component."""
        connections = get_connections_for_component(self.config, "reactor1")
        self.assertEqual(len(connections), 2)  # mfc1 (target) and mfc2 (source)
        
        connection_ids = {conn['id'] for conn in connections}
        self.assertIn("mfc1", connection_ids)
        self.assertIn("mfc2", connection_ids)
    
    def test_get_connections_for_component_none(self):
        """Test getting connections for component with no connections."""
        # Create a component not in any connections
        config = self.config.copy()
        config["components"].append({"id": "isolated", "type": "Reactor"})
        
        connections = get_connections_for_component(config, "isolated")
        self.assertEqual(len(connections), 0)


class TestConfigurationSaving(unittest.TestCase):
    """Test configuration saving functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.valid_config = {
            "metadata": {"name": "Test Configuration", "version": "1.0"},
            "simulation": {"mechanism": "gri30.yaml", "time_step": 0.001, "max_time": 10.0},
            "components": [
                {"id": "reactor1", "type": "IdealGasReactor", "properties": {"temperature": 1000}},
                {"id": "res1", "type": "Reservoir", "properties": {"temperature": 300}}
            ],
            "connections": [
                {"id": "mfc1", "type": "MassFlowController", "source": "res1", "target": "reactor1", "properties": {"mass_flow_rate": 0.1}}
            ]
        }
    
    def test_save_valid_config_yaml(self):
        """Test saving valid configuration to YAML."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            try:
                save_config_to_file(self.valid_config, f.name, 'yaml')
                
                # Verify file was created and can be loaded
                self.assertTrue(os.path.exists(f.name))
                loaded_config = load_config_file(f.name)
                self.assertEqual(loaded_config['metadata']['name'], "Test Configuration")
            finally:
                if os.path.exists(f.name):
                    os.unlink(f.name)
    
    def test_save_valid_config_json(self):
        """Test saving valid configuration to JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            try:
                save_config_to_file(self.valid_config, f.name, 'json')
                
                # Verify file was created and can be loaded
                self.assertTrue(os.path.exists(f.name))
                loaded_config = load_config_file(f.name)
                self.assertEqual(loaded_config['metadata']['name'], "Test Configuration")
            finally:
                if os.path.exists(f.name):
                    os.unlink(f.name)
    
    def test_save_invalid_config(self):
        """Test error when saving invalid configuration."""
        invalid_config = {"components": [{"id": "test"}]}  # Missing type
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            try:
                with self.assertRaises(ConfigurationError):
                    save_config_to_file(invalid_config, f.name, 'yaml')
            finally:
                if os.path.exists(f.name):
                    os.unlink(f.name)
    
    def test_save_yaml_without_pyyaml(self):
        """Test error when saving YAML without PyYAML."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            try:
                with patch('boulder.config.YAML_AVAILABLE', False):
                    with self.assertRaises(ImportError) as cm:
                        save_config_to_file(self.valid_config, f.name, 'yaml')
                    
                    self.assertIn("PyYAML is required", str(cm.exception))
            finally:
                if os.path.exists(f.name):
                    os.unlink(f.name)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and corner scenarios."""
    
    def test_duplicate_component_ids(self):
        """Test handling of duplicate component IDs."""
        config = {
            "components": [
                {"id": "reactor1", "type": "IdealGasReactor"},
                {"id": "reactor1", "type": "Reservoir"}  # Duplicate ID
            ],
            "connections": []
        }
        
        # Current implementation doesn't explicitly check for duplicate IDs
        # but the reference validation will work with the first occurrence
        validate_config_structure(config)
        validate_component_references(config)
    
    def test_self_referencing_connection(self):
        """Test connection where source and target are the same."""
        config = {
            "components": [
                {"id": "reactor1", "type": "IdealGasReactor"}
            ],
            "connections": [
                {"id": "loop", "type": "Valve", "source": "reactor1", "target": "reactor1"}
            ]
        }
        
        # Should be valid - component can connect to itself
        validate_config_structure(config)
        validate_component_references(config)
    
    def test_very_large_config(self):
        """Test handling of large configuration."""
        # Create a config with many components and connections
        components = []
        connections = []
        
        for i in range(100):
            components.append({"id": f"component_{i}", "type": "Reactor"})
            if i > 0:
                connections.append({
                    "id": f"connection_{i}",
                    "type": "Pipe",
                    "source": f"component_{i-1}",
                    "target": f"component_{i}"
                })
        
        config = {
            "components": components,
            "connections": connections
        }
        
        # Should handle large configs without issues
        validate_config_structure(config)
        validate_component_references(config)


if __name__ == '__main__':
    unittest.main(verbosity=2) 