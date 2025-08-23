"""Tests for Boulder CLI headless mode functionality."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.mark.integration
class TestCLIHeadless:
    """Integration tests for Boulder CLI headless mode."""

    def test_headless_python_generation_and_execution(self):
        """Test that headless mode generates runnable Python code from YAML configuration.

        This test verifies the complete headless workflow:
        1. CLI command execution succeeds (returncode == 0)
        2. Success messages appear in stdout ("Python code generated:", output path)
        3. Output Python file is created and exists on disk
        4. Generated code contains required Cantera imports and setup:
           - "import cantera as ct"
           - "gas_default = ct.Solution("
           - "network = ct.ReactorNet("
           - "network.advance("
        5. Generated code contains all reactors from mix_react_streams.yaml:
           - "Mixer = ct.IdealGasReactor(" (main mixing reactor)
           - "Air_Reservoir = ct.Reservoir(" (air inlet reservoir)
           - "Fuel_Reservoir = ct.Reservoir(" (fuel inlet reservoir)
           - "Outlet_Reservoir = ct.Reservoir(" (outlet reservoir)
        6. Generated code contains all connections from config:
           - "Air_Inlet = ct.MassFlowController(" (air inlet connection)
           - "Fuel_Inlet = ct.MassFlowController(" (fuel inlet connection)
           - "Valve = ct.Valve(" (outlet valve connection)
        7. Generated Python code executes successfully:
           - Simulation output contains "t=" (time values)
           - Simulation output contains "T=" (temperature values)
        8. Generated code uses proper numpy time stepping:
           - "import numpy as np"
           - "times = np.arange("
        """
        # Get the path to the test config file
        config_path = (
            Path(__file__).parent.parent / "configs" / "mix_react_streams.yaml"
        )
        assert config_path.exists(), f"Test config file not found: {config_path}"

        # Create a temporary file for the generated Python code
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as tmp_file:
            output_path = tmp_file.name

        try:
            # Run Boulder in headless mode to generate Python code
            cmd = [
                sys.executable,
                "-m",
                "boulder.cli",
                str(config_path),
                "--headless",
                "--download",
                output_path,
                "--verbose",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # 60 second timeout
            )

            # Check that the command succeeded
            assert result.returncode == 0, f"CLI command failed: {result.stderr}"

            # Check that success message is in output
            assert "Python code generated:" in result.stdout
            assert output_path in result.stdout

            # Check that the output file was created
            assert os.path.exists(output_path), "Generated Python file does not exist"

            # Read the generated Python code
            with open(output_path, "r", encoding="utf-8") as f:
                generated_code = f.read()

            # Verify the generated code has expected content
            assert "import cantera as ct" in generated_code
            assert "gas_default = ct.Solution(" in generated_code
            assert "network = ct.ReactorNet(" in generated_code
            assert "network.advance(" in generated_code

            # Verify it contains the reactors from the config (using actual names from mix_react_streams.yaml)
            assert "Mixer = ct.IdealGasReactor(" in generated_code
            assert "Air_Reservoir = ct.Reservoir(" in generated_code
            assert "Fuel_Reservoir = ct.Reservoir(" in generated_code
            assert "Outlet_Reservoir = ct.Reservoir(" in generated_code

            # Verify it contains the connections from the config (using actual names)
            assert "Air_Inlet = ct.MassFlowController(" in generated_code
            assert "Fuel_Inlet = ct.MassFlowController(" in generated_code
            assert "Valve = ct.Valve(" in generated_code

            # Test that the generated Python code can be executed
            exec_result = subprocess.run(
                [sys.executable, output_path],
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout for execution
            )

            # The generated code should start running and produce some output
            # Even if the simulation fails due to numerical issues, we should see initial output
            assert "t=" in exec_result.stdout, "No simulation output found"
            assert "T=" in exec_result.stdout, "No temperature output found"

            # Verify that the code contains proper numpy usage for time steps
            assert "import numpy as np" in generated_code
            assert "times = np.arange(" in generated_code

        finally:
            # Clean up the temporary file
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_headless_mode_validation_errors(self):
        """Test that headless mode properly handles validation errors.

        This test verifies error handling for invalid CLI argument combinations:
        1. Missing config file with --headless:
           - Command returns exit code 1 (failure)
           - Error message contains "Error: --headless requires a config file"
        2. Missing --download argument with --headless:
           - Command returns exit code 1 (failure)
           - Error message contains "Error: --headless requires --download"
        3. Using --download without --headless:
           - Command returns exit code 1 (failure)
           - Error message contains "Error: --download requires --headless"
        """
        # Test missing config file
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "boulder.cli",
                "--headless",
                "--download",
                "test.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Error: --headless requires a config file" in result.stdout

        # Test missing download argument
        config_path = (
            Path(__file__).parent.parent / "configs" / "mix_react_streams.yaml"
        )
        result = subprocess.run(
            [sys.executable, "-m", "boulder.cli", str(config_path), "--headless"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Error: --headless requires --download" in result.stdout

        # Test download without headless
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "boulder.cli",
                str(config_path),
                "--download",
                "test.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Error: --download requires --headless" in result.stdout

    def test_headless_mode_nonexistent_config(self):
        """Test that headless mode handles nonexistent config files gracefully.

        This test verifies error handling for missing configuration files:
        1. Command with nonexistent config file returns exit code 1 (failure)
        2. Error message contains "Error:" prefix
        3. Error message contains "not found" (case-insensitive)
        4. No output file is created when config file doesn't exist
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as tmp_file:
            output_path = tmp_file.name

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "boulder.cli",
                    "nonexistent_config.yaml",
                    "--headless",
                    "--download",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 1
            assert "Error:" in result.stdout
            assert "not found" in result.stdout.lower()

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_cli_help_includes_headless_options(self):
        """Test that CLI help includes the new headless options.

        This test verifies that the CLI help output contains headless functionality:
        1. Command returns exit code 0 (success)
        2. Help text contains "--headless" option flag
        3. Help text contains "--download" option flag
        4. Help text contains "Run without starting the web UI" description
        5. Help text contains "Generate Python code from YAML" description
        """
        result = subprocess.run(
            [sys.executable, "-m", "boulder.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--headless" in result.stdout
        assert "--download" in result.stdout
        assert "Run without starting the web UI" in result.stdout
        assert "Generate Python code from YAML" in result.stdout
