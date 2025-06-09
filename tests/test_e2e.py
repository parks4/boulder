"""End-to-end tests for Boulder Dash application."""

import time

import pytest
from selenium.webdriver.common.keys import Keys


@pytest.mark.e2e
class TestBoulderE2E:
    """End-to-end tests for Boulder application."""

    @pytest.fixture
    def dash_duo(self, dash_duo):
        """Setup the app for testing."""
        # Import the app directly
        from boulder.app import app

        dash_duo.start_server(app)
        return dash_duo

    def test_add_reactor_flow(self, dash_duo):
        """Test the complete add reactor workflow."""
        # Wait for app to load
        dash_duo.wait_for_element("#open-reactor-modal", timeout=10)

        # Click "Add Reactor" button
        dash_duo.find_element("#open-reactor-modal").click()

        # Wait for modal to open
        dash_duo.wait_for_element("#add-reactor-modal", timeout=5)

        # Fill in reactor details
        reactor_id_input = dash_duo.find_element("#reactor-id")
        reactor_id_input.clear()
        reactor_id_input.send_keys("test-reactor-1")

        # Select reactor type
        reactor_type_select = dash_duo.find_element("#reactor-type")
        dash_duo.select_dcc_dropdown("#reactor-type", "IdealGasReactor")

        # Fill temperature
        temp_input = dash_duo.find_element("#reactor-temp")
        temp_input.clear()
        temp_input.send_keys("500")

        # Fill pressure
        pressure_input = dash_duo.find_element("#reactor-pressure")
        pressure_input.clear()
        pressure_input.send_keys("200000")

        # Fill composition
        composition_input = dash_duo.find_element("#reactor-composition")
        composition_input.clear()
        composition_input.send_keys("CH4:1,O2:2,N2:7.52")

        # Submit the form
        dash_duo.find_element("#add-reactor").click()

        # Wait for success notification
        dash_duo.wait_for_text_to_equal(
            "#notification-toast", "Added IdealGasReactor test-reactor-1", timeout=5
        )

        # Verify reactor appears in graph
        dash_duo.wait_for_element(
            "div[data-cy='node'][data-id='test-reactor-1']", timeout=5
        )

    def test_add_reactor_validation(self, dash_duo):
        """Test reactor form validation."""
        dash_duo.wait_for_element("#open-reactor-modal", timeout=10)
        dash_duo.find_element("#open-reactor-modal").click()

        # Try to submit empty form
        dash_duo.find_element("#add-reactor").click()

        # Should show error notification
        dash_duo.wait_for_text_to_equal(
            "#notification-toast", "Please fill in all fields", timeout=5
        )

    def test_add_mfc_flow(self, dash_duo):
        """Test adding a Mass Flow Controller."""
        # First add two reactors
        self._add_test_reactor(dash_duo, "reactor-1")
        self._add_test_reactor(dash_duo, "reactor-2")

        # Click "Add MFC" button
        dash_duo.find_element("#open-mfc-modal").click()
        dash_duo.wait_for_element("#add-mfc-modal", timeout=5)

        # Fill MFC details
        dash_duo.find_element("#mfc-id").send_keys("mfc-1")
        dash_duo.select_dcc_dropdown("#mfc-source", "reactor-1")
        dash_duo.select_dcc_dropdown("#mfc-target", "reactor-2")
        dash_duo.find_element("#mfc-flow-rate").send_keys("0.005")

        # Submit
        dash_duo.find_element("#add-mfc").click()

        # Verify success
        dash_duo.wait_for_contains_text(
            "#notification-toast", "Added MFC mfc-1", timeout=5
        )

    def test_config_upload(self, dash_duo):
        """Test configuration file upload."""
        # Create a test config file
        test_config = {
            "components": [
                {
                    "id": "uploaded-reactor",
                    "type": "IdealGasReactor",
                    "properties": {
                        "temperature": 300,
                        "pressure": 101325,
                        "composition": "O2:1,N2:3.76",
                    },
                }
            ],
            "connections": [],
        }

        # Upload config (this would need to be adapted based on how file upload is implemented)
        # For now, test the config display
        dash_duo.wait_for_element("#config-upload-area", timeout=10)

    def test_config_json_edit(self, dash_duo):
        """Test JSON configuration editing."""
        # Click on config file name to open modal
        dash_duo.wait_for_element("#config-file-name-span", timeout=10)
        dash_duo.find_element("#config-file-name-span").click()

        # Wait for modal
        dash_duo.wait_for_element("#config-json-modal", timeout=5)

        # Click edit button
        dash_duo.find_element("#edit-config-json-btn").click()

        # Wait for textarea to appear
        dash_duo.wait_for_element("#config-json-edit-textarea", timeout=5)

        # Edit the JSON
        textarea = dash_duo.find_element("#config-json-edit-textarea")
        current_text = textarea.get_attribute("value")
        # Modify the JSON (add a comment or change a value)
        modified_text = current_text.replace('"temperature": 300', '"temperature": 350')
        textarea.clear()
        textarea.send_keys(modified_text)

        # Save changes
        dash_duo.find_element("#save-config-json-edit-btn").click()

        # Verify success
        dash_duo.wait_for_contains_text(
            "#notification-toast", "Configuration updated", timeout=5
        )

    def test_graph_node_selection(self, dash_duo):
        """Test selecting nodes in the graph."""
        # Add a reactor first
        self._add_test_reactor(dash_duo, "test-node")

        # Click on the node in the graph
        node = dash_duo.wait_for_element(
            "div[data-cy='node'][data-id='test-node']", timeout=5
        )
        node.click()

        # Verify properties panel updates
        dash_duo.wait_for_element("#properties-panel", timeout=5)
        # Check if properties are displayed
        assert "test-node" in dash_duo.find_element("#properties-panel").text

    def test_simulation_run(self, dash_duo):
        """Test running a simulation."""
        # Setup: Add reactors and connections
        self._add_test_reactor(dash_duo, "sim-reactor-1")
        self._add_test_reactor(dash_duo, "sim-reactor-2")

        # Run simulation
        dash_duo.find_element("#run-simulation").click()

        # Verify simulation started
        dash_duo.wait_for_contains_text(
            "#notification-toast", "Simulation successfully started", timeout=10
        )

        # Check if plots are generated
        dash_duo.wait_for_element("#temperature-plot", timeout=15)
        dash_duo.wait_for_element("#pressure-plot", timeout=5)

    def test_keyboard_shortcuts(self, dash_duo):
        """Test keyboard shortcuts (e.g., Ctrl+Enter for simulation)."""
        # Add some reactors first
        self._add_test_reactor(dash_duo, "shortcut-reactor")

        # Use Ctrl+Enter to run simulation
        body = dash_duo.find_element("body")
        body.send_keys(Keys.CONTROL + Keys.ENTER)

        # Verify simulation runs
        dash_duo.wait_for_contains_text(
            "#notification-toast", "Simulation successfully started", timeout=10
        )

    def test_error_handling(self, dash_duo):
        """Test error handling scenarios."""
        # Test duplicate reactor ID
        self._add_test_reactor(dash_duo, "duplicate-reactor")

        # Try to add same reactor again
        dash_duo.find_element("#open-reactor-modal").click()
        dash_duo.wait_for_element("#add-reactor-modal", timeout=5)

        # Fill with same ID
        reactor_id_input = dash_duo.find_element("#reactor-id")
        reactor_id_input.clear()
        reactor_id_input.send_keys("duplicate-reactor")

        # Fill other required fields
        dash_duo.select_dcc_dropdown("#reactor-type", "IdealGasReactor")
        dash_duo.find_element("#reactor-temp").clear()
        dash_duo.find_element("#reactor-temp").send_keys("300")
        dash_duo.find_element("#reactor-pressure").clear()
        dash_duo.find_element("#reactor-pressure").send_keys("101325")
        dash_duo.find_element("#reactor-composition").clear()
        dash_duo.find_element("#reactor-composition").send_keys("O2:1,N2:3.76")

        dash_duo.find_element("#add-reactor").click()

        # Verify error message
        dash_duo.wait_for_contains_text(
            "#notification-toast", "already exists", timeout=5
        )

    def _add_test_reactor(self, dash_duo, reactor_id):
        """Helper method to add a test reactor."""
        dash_duo.find_element("#open-reactor-modal").click()
        dash_duo.wait_for_element("#add-reactor-modal", timeout=5)

        # Fill reactor details
        reactor_id_input = dash_duo.find_element("#reactor-id")
        reactor_id_input.clear()
        reactor_id_input.send_keys(reactor_id)

        dash_duo.select_dcc_dropdown("#reactor-type", "IdealGasReactor")

        temp_input = dash_duo.find_element("#reactor-temp")
        temp_input.clear()
        temp_input.send_keys("300")

        pressure_input = dash_duo.find_element("#reactor-pressure")
        pressure_input.clear()
        pressure_input.send_keys("101325")

        composition_input = dash_duo.find_element("#reactor-composition")
        composition_input.clear()
        composition_input.send_keys("O2:1,N2:3.76")

        dash_duo.find_element("#add-reactor").click()

        # Wait for success
        dash_duo.wait_for_contains_text(
            "#notification-toast", f"Added IdealGasReactor {reactor_id}", timeout=5
        )


# Performance tests
@pytest.mark.slow
@pytest.mark.e2e
class TestBoulderPerformance:
    """Performance tests for Boulder application."""

    def test_large_graph_performance(self, dash_duo):
        """Test performance with many nodes."""
        # Add multiple reactors and measure time
        start_time = time.time()

        for i in range(10):
            self._add_test_reactor(dash_duo, f"perf-reactor-{i}")

        end_time = time.time()
        assert end_time - start_time < 30  # Should complete within 30 seconds

    def test_simulation_performance(self, dash_duo):
        """Test simulation performance."""
        # Setup complex network
        for i in range(5):
            self._add_test_reactor(dash_duo, f"sim-perf-{i}")

        # Run simulation and measure time
        start_time = time.time()
        dash_duo.find_element("#run-simulation").click()
        dash_duo.wait_for_contains_text(
            "#notification-toast", "Simulation successfully started", timeout=30
        )
        end_time = time.time()

        assert end_time - start_time < 25  # Should complete within 25 seconds
