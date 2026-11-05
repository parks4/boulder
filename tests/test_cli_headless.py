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

    def test_headless_python_generation_and_execution(self, tmp_path):
        """Test that headless mode generates runnable Python code from YAML configuration.

        This test verifies the complete headless workflow:
        1. CLI command execution succeeds (returncode == 0)
        2. Success messages appear in stdout ("Python code generated:", output path)
        3. Output Python file is created and exists on disk
        4. Generated code is the runner-based script: it embeds the resolved YAML,
           lists the class each node runs and solves stage by stage:
           - "from boulder.runner import BoulderRunner"
           - one ``runner.solve_stage`` call per stage
           - a per-stage class table and the ``check_classes`` check
        5. Generated code reports the converged per-reactor states
           (``build_network`` always routes through the staged solver, so the
           downloadable script does not re-advance the network; instead it
           iterates over ``network.reactors`` to print ``T``/``P``).
        6. Generated Python code executes successfully and prints reactor
           states:
           - Simulation stdout contains "Reactor" (header line)
           - Simulation stdout contains "T [K]" (header label)
        """
        # Get the path to the test config file
        config_path = (
            Path(__file__).parent.parent / "configs" / "mix_react_streams.yaml"
        )
        assert config_path.exists(), f"Test config file not found: {config_path}"

        # The generated script goes to pytest's own directory: a script run from
        # the system temp dir would import whatever stray module sits there.
        output_path = str(tmp_path / "generated.py")

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
                encoding="utf-8",
                errors="replace",
                timeout=60,  # 60 second timeout
            )

            # Check that the command succeeded
            stderr = result.stderr or ""
            assert result.returncode == 0, f"CLI command failed: {stderr}"

            # Check that success message is in output (stdout can be None if decode failed)
            stdout = result.stdout or ""
            assert "Python code generated:" in stdout
            assert output_path in stdout

            # Check that the output file was created
            assert os.path.exists(output_path), "Generated Python file does not exist"

            # Read the generated Python code
            with open(output_path, "r", encoding="utf-8") as f:
                generated_code = f.read()

            # The download is the runner-based script: the solved config, a class
            # table per stage and one ``runner.solve_stage`` call per stage.
            assert "from boulder.runner import BoulderRunner" in generated_code
            assert "CONFIG_YAML = '''" in generated_code
            assert "runner.solve_stage(" in generated_code
            assert "# Classes that run, per stage" in generated_code
            assert "cantera.reactor." in generated_code
            assert "check_classes(stages[" in generated_code
            assert "reactors = {}" not in generated_code

            # Test that the generated Python code can be executed
            exec_result = subprocess.run(
                [sys.executable, output_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,  # 30 second timeout for execution
                # The script imports Boulder: this checkout's, not another install's.
                env={
                    **os.environ,
                    "PYTHONPATH": os.pathsep.join(
                        [
                            str(Path(__file__).resolve().parents[1]),
                            os.environ.get("PYTHONPATH", ""),
                        ]
                    ),
                },
            )

            # The generated code should report the converged reactor states
            exec_stdout = exec_result.stdout or ""
            assert exec_result.returncode == 0, exec_result.stderr
            assert "Reactor" in exec_stdout, "No reactor output header found"
            assert "T [K]" in exec_stdout, "No temperature column found"

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
        2. Missing --run/--download argument with --headless:
           - Command returns exit code 1 (failure)
           - Error message contains "Error: --headless requires --run"
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
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 1
        assert "Error: --headless requires a config file" in (result.stdout or "")

        # Test missing download argument
        config_path = (
            Path(__file__).parent.parent / "configs" / "mix_react_streams.yaml"
        )
        result = subprocess.run(
            [sys.executable, "-m", "boulder.cli", str(config_path), "--headless"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 1
        assert "Error: --headless requires --run (solve the case) or --download" in (
            result.stdout or ""
        )

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
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 1
        assert "Error: --download requires --headless" in (result.stdout or "")

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
                encoding="utf-8",
                errors="replace",
            )

            out = result.stdout or ""
            assert result.returncode == 1
            assert "Error:" in out
            assert "not found" in out.lower()

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
            encoding="utf-8",
            errors="replace",
        )

        out = result.stdout or ""
        assert result.returncode == 0
        assert "--headless" in out
        assert "--download" in out
        assert "Run without starting the web UI" in out
        assert "Generate Python code from YAML" in out
        assert "Developers:" in out
        assert "npm run build" in out
