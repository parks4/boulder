"""Integration tests for Boulder web interface with configuration files.

These tests verify that the web interface can start successfully with various
configuration files and that all callbacks are properly registered.
"""

import os
from pathlib import Path

import pytest

from boulder.app import create_app


@pytest.mark.integration
class TestWebInterfaceIntegration:
    """Integration tests for web interface with configuration files."""

    def test_app_starts_with_default_config(self):
        """Test that the app starts successfully with default configuration."""
        app = create_app()
        assert app is not None
        assert hasattr(app, "layout")
        assert hasattr(app, "callback_map")
        assert len(app.callback_map) > 0

    def test_app_starts_with_mix_react_streams_config(self):
        """Test that the app starts successfully with mix_react_streams.yaml config.

        This test specifically targets the configuration file that was causing
        callback registration errors in the web interface.
        """
        # Get the path to the test config file
        config_path = (
            Path(__file__).parent.parent / "configs" / "mix_react_streams.yaml"
        )
        assert config_path.exists(), f"Config file not found: {config_path}"

        # Set environment variable to load the config
        original_env = os.environ.get("BOULDER_CONFIG_PATH")
        try:
            os.environ["BOULDER_CONFIG_PATH"] = str(config_path)

            # Import app module to trigger config loading
            # We need to reload the module to pick up the new environment variable
            import importlib

            import boulder.app

            importlib.reload(boulder.app)

            app = boulder.app.create_app()
            assert app is not None
            assert hasattr(app, "layout")
            assert hasattr(app, "callback_map")
            assert len(app.callback_map) > 0

            # Verify that all expected callback outputs exist in the layout
            layout_str = str(app.layout)

            # Check for simulation plot components that were causing callback errors
            required_components = [
                "temperature-plot",
                "pressure-plot",
                "species-plot",
                "simulation-data",
                "simulation-error-display",
                "simulation-error-pane",
                "error-tab-pane",
                "last-sim-python-code",
            ]

            for component_id in required_components:
                assert component_id in layout_str, (
                    f"Required component '{component_id}' not found in layout. "
                    f"This could cause callback registration errors."
                )

        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["BOULDER_CONFIG_PATH"] = original_env
            elif "BOULDER_CONFIG_PATH" in os.environ:
                del os.environ["BOULDER_CONFIG_PATH"]

            # Reload app module to restore original state
            import importlib

            import boulder.app

            importlib.reload(boulder.app)

    def test_app_starts_with_grouped_nodes_config(self):
        """Test that the app starts successfully with grouped_nodes.yaml config."""
        config_path = Path(__file__).parent.parent / "configs" / "grouped_nodes.yaml"
        assert config_path.exists(), f"Config file not found: {config_path}"

        original_env = os.environ.get("BOULDER_CONFIG_PATH")
        try:
            os.environ["BOULDER_CONFIG_PATH"] = str(config_path)

            import importlib

            import boulder.app

            importlib.reload(boulder.app)

            app = boulder.app.create_app()
            assert app is not None
            assert len(app.callback_map) > 0

        finally:
            if original_env is not None:
                os.environ["BOULDER_CONFIG_PATH"] = original_env
            elif "BOULDER_CONFIG_PATH" in os.environ:
                del os.environ["BOULDER_CONFIG_PATH"]

            import importlib

            import boulder.app

            importlib.reload(boulder.app)

    def test_callback_registration_completeness(self):
        """Test that all callback outputs have corresponding components in layout."""
        app = create_app()
        layout_str = str(app.layout)

        # Extract all callback output IDs
        callback_output_ids = set()
        for callback_spec in app.callback_map.keys():
            # Parse the callback spec string to extract output IDs
            # Format is typically like "..component-id.property.."
            spec_str = str(callback_spec)
            # Simple regex-like extraction of component IDs between dots
            parts = spec_str.split("..")
            for part in parts:
                if part and "." in part:
                    component_id = part.split(".")[0]
                    if component_id and not component_id.startswith("_"):
                        callback_output_ids.add(component_id)

        # Check that all callback output components exist in layout
        missing_components = []
        for component_id in callback_output_ids:
            if component_id not in layout_str:
                missing_components.append(component_id)

        assert not missing_components, (
            f"Callback outputs reference components not found in layout: {missing_components}. "
            f"This will cause 'Callback function not found for output' errors."
        )

    def test_simulation_callback_outputs_exist(self):
        """Test that all simulation callback outputs have corresponding layout components."""
        app = create_app()
        layout_str = str(app.layout)

        # These are the specific components that were causing the callback error
        simulation_components = [
            "temperature-plot",
            "pressure-plot",
            "species-plot",
            "temperature-plot-container",
            "pressure-plot-container",
            "species-plot-container",
            "last-sim-python-code",
            "simulation-results-card",
            "simulation-data",
            "simulation-error-display",
            "simulation-error-pane",
            "error-tab-pane",
            "simulation-progress-interval",
            "simulation-running",
            "simulation-timer",
        ]

        missing_components = []
        for component_id in simulation_components:
            if component_id not in layout_str:
                missing_components.append(component_id)

        assert not missing_components, (
            f"Simulation callback components not found in layout: {missing_components}. "
            f"This will cause the 'Callback function not found for output' error."
        )
