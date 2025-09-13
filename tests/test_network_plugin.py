"""Tests for the Network plugin functionality."""

import pytest
from unittest.mock import patch, MagicMock

from boulder.network_plugin import NetworkPlugin
from boulder.output_pane_plugins import OutputPaneContext
from boulder.live_simulation import update_live_simulation, clear_live_simulation


class TestNetworkPlugin:
    """Test cases for the Network plugin."""

    def setup_method(self):
        """Set up test fixtures."""
        self.plugin = NetworkPlugin()
        clear_live_simulation()

    def teardown_method(self):
        """Clean up after tests."""
        clear_live_simulation()

    def test_plugin_properties(self):
        """Test basic plugin properties."""
        assert self.plugin.plugin_id == "network-visualization"
        assert self.plugin.tab_label == "Network"
        assert self.plugin.tab_icon == "diagram-3"
        assert not self.plugin.requires_selection
        assert "reactor" in self.plugin.supported_element_types
        assert "connection" in self.plugin.supported_element_types

    def test_is_available_no_simulation(self):
        """Test plugin availability when no simulation data exists."""
        context = OutputPaneContext(
            simulation_data=None,
            config={},
            theme="light"
        )
        assert not self.plugin.is_available(context)

    def test_is_available_no_live_simulation(self):
        """Test plugin availability when simulation data exists but no live simulation."""
        context = OutputPaneContext(
            simulation_data={"results": {"time": [0, 1]}},
            config={},
            theme="light"
        )
        assert not self.plugin.is_available(context)

    def test_is_available_with_live_simulation(self):
        """Test plugin availability when live simulation is available."""
        # Mock a network
        mock_network = MagicMock()
        mock_reactor = MagicMock()
        mock_reactor.name = "test_reactor"
        mock_network.reactors = [mock_reactor]

        # Update live simulation
        update_live_simulation(
            network=mock_network,
            reactors={"test_reactor": mock_reactor},
            mechanism="gri30.yaml"
        )

        context = OutputPaneContext(
            simulation_data={"results": {"time": [0, 1]}},
            config={},
            theme="light"
        )
        assert self.plugin.is_available(context)

    def test_create_content_no_live_simulation(self):
        """Test content creation when no live simulation is available."""
        context = OutputPaneContext(
            simulation_data={"results": {"time": [0, 1]}},
            config={},
            theme="light"
        )
        
        content = self.plugin.create_content(context)
        
        # Should return a div with error message
        assert hasattr(content, 'children')
        # Check that it contains the expected error message
        content_str = str(content)
        assert "Network Not Available" in content_str

    @patch('boulder.network_plugin.get_live_simulation')
    def test_create_content_network_drawing_success(self, mock_get_live_sim):
        """Test successful network diagram generation."""
        # Mock live simulation
        mock_live_sim = MagicMock()
        mock_live_sim.is_available.return_value = True
        
        # Mock network
        mock_network = MagicMock()
        mock_live_sim.get_network.return_value = mock_network
        
        # Mock the _generate_network_diagram method to return success
        with patch.object(self.plugin, '_generate_network_diagram') as mock_generate:
            mock_generate.return_value = ("base64encodedimage", None)
            
            mock_get_live_sim.return_value = mock_live_sim
            
            context = OutputPaneContext(
                simulation_data={"results": {"time": [0, 1]}},
                config={},
                theme="light"
            )
            
            content = self.plugin.create_content(context)
            
            # Should return a Card with the network diagram
            assert hasattr(content, 'children')
            content_str = str(content)
            assert "Reactor Network Structure" in content_str

    @patch('boulder.network_plugin.get_live_simulation')
    def test_create_content_network_drawing_failure(self, mock_get_live_sim):
        """Test network diagram generation failure."""
        # Mock live simulation
        mock_live_sim = MagicMock()
        mock_live_sim.is_available.return_value = True
        
        # Mock network
        mock_network = MagicMock()
        mock_live_sim.get_network.return_value = mock_network
        
        # Mock the _generate_network_diagram method to return failure
        with patch.object(self.plugin, '_generate_network_diagram') as mock_generate:
            mock_generate.return_value = (None, "Graphviz not available")
            
            mock_get_live_sim.return_value = mock_live_sim
            
            context = OutputPaneContext(
                simulation_data={"results": {"time": [0, 1]}},
                config={},
                theme="light"
            )
            
            content = self.plugin.create_content(context)
            
            # Should return a div with error message
            content_str = str(content)
            assert "Network Diagram Generation Failed" in content_str
            assert "Graphviz not available" in content_str

    def test_generate_network_diagram_no_graphviz(self):
        """Test network diagram generation when graphviz is not available."""
        mock_network = MagicMock()
        
        with patch('builtins.__import__', side_effect=ImportError("No module named 'graphviz'")):
            encoded_image, error_message = self.plugin._generate_network_diagram(mock_network)
            
            assert encoded_image is None
            assert "Graphviz not available" in error_message

    def test_generate_network_diagram_success(self):
        """Test successful network diagram generation."""
        mock_network = MagicMock()
        
        # Mock the draw method to return a mock diagram
        mock_diagram = MagicMock()
        mock_diagram.pipe.return_value = b'fake_png_data'
        mock_network.draw.return_value = mock_diagram
        
        # Mock the graphviz import inside the method
        with patch('builtins.__import__') as mock_import:
            # Make import succeed
            mock_import.return_value = MagicMock()
            
            encoded_image, error_message = self.plugin._generate_network_diagram(mock_network)
            
            assert encoded_image is not None
            assert error_message is None
            # Check that the image is base64 encoded
            import base64
            try:
                base64.b64decode(encoded_image)
            except Exception:
                pytest.fail("Returned image is not valid base64")

    def test_generate_network_diagram_draw_failure(self):
        """Test network diagram generation when draw() fails."""
        mock_network = MagicMock()
        mock_network.draw.side_effect = Exception("Network drawing failed")
        
        # Mock the graphviz import inside the method
        with patch('builtins.__import__') as mock_import:
            # Make import succeed
            mock_import.return_value = MagicMock()
            
            encoded_image, error_message = self.plugin._generate_network_diagram(mock_network)
            
            assert encoded_image is None
            assert "Network diagram generation failed" in error_message
            assert "Network drawing failed" in error_message
