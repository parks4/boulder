"""
Tests for smart detection of comments in Python files for sim2stone functionality.

This module tests the enhanced comment parsing and object detection system
that automatically extracts descriptions from Python source files.
"""

import os
import tempfile
import textwrap

import cantera as ct
import pytest

from boulder.sim2stone import (
    _parse_python_comments,
    _smart_extract_object_comments,
    sim_to_stone_yaml,
)


def create_temp_python_file(content: str) -> str:
    """Create a temporary Python file with given content and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(textwrap.dedent(content))
        f.flush()
        return f.name


def cleanup_temp_file(filepath: str) -> None:
    """Clean up temporary file, ignoring Windows permission errors."""
    try:
        os.unlink(filepath)
    except (OSError, PermissionError):
        pass  # Ignore cleanup errors on Windows


class TestPythonCommentParsing:
    """Test basic Python comment parsing functionality."""

    def test_parse_docstring(self):
        """Test extraction of file-level docstring."""
        temp_file = create_temp_python_file('''
            """
            Test module docstring
            with multiple lines
            """

            import cantera as ct

            gas = ct.Solution('gri30.yaml')
        ''')

        try:
            metadata = _parse_python_comments(temp_file)
            assert (
                metadata["file_description"]
                == "Test module docstring\nwith multiple lines"
            )
            assert metadata["source_file"] == os.path.basename(temp_file)
        finally:
            cleanup_temp_file(temp_file)

    def test_parse_inline_comments(self):
        """Test extraction of inline comments."""
        temp_file = create_temp_python_file("""
            import cantera as ct

            gas = ct.Solution('gri30.yaml')  # Main gas solution
            temp = 300.0  # Temperature in Kelvin
        """)

        try:
            metadata = _parse_python_comments(temp_file)
            assert "gas" in metadata["variable_comments"]
            assert metadata["variable_comments"]["gas"] == "Main gas solution"
            assert "temp" in metadata["variable_comments"]
            assert metadata["variable_comments"]["temp"] == "Temperature in Kelvin"
        finally:
            cleanup_temp_file(temp_file)

    def test_parse_standalone_comments(self):
        """Test extraction of standalone comments above assignments."""
        temp_file = create_temp_python_file("""
            import cantera as ct

            # This is a gas solution for methane
            gas = ct.Solution('gri30.yaml')

            # Temperature setting
            temp = 300.0
        """)

        try:
            metadata = _parse_python_comments(temp_file)
            assert "gas" in metadata["variable_comments"]
            assert (
                metadata["variable_comments"]["gas"]
                == "This is a gas solution for methane"
            )
            assert "temp" in metadata["variable_comments"]
            assert metadata["variable_comments"]["temp"] == "Temperature setting"
        finally:
            cleanup_temp_file(temp_file)

    def test_nonexistent_file(self):
        """Test handling of nonexistent files."""
        metadata = _parse_python_comments("nonexistent_file.py")
        assert metadata == {}


class TestSmartObjectDetection:
    """Test smart object detection from reactor networks."""

    def test_single_reactor_detection(self):
        """Test detection of a single reactor with comments."""
        temp_file = create_temp_python_file("""
            '''Test reactor network'''
            import cantera as ct

            # Create gas solution
            gas = ct.Solution('gri30.yaml')
            gas.TPX = 300, ct.one_atm, 'CH4:1'

            # Main reactor for combustion
            reactor = ct.IdealGasReactor(gas, name="Main Reactor")

            # Create network
            sim = ct.ReactorNet([reactor])
        """)

        try:
            # Execute the file to create the network
            exec_globals = {}
            with open(temp_file, "r") as f:
                exec(f.read(), exec_globals)

            sim = exec_globals["sim"]
            comments = _smart_extract_object_comments(temp_file, sim)

            assert "reactor" in comments
            assert comments["reactor"] == "Main reactor for combustion"
            assert "Main Reactor" in comments
            assert comments["Main Reactor"] == "Main reactor for combustion"

        finally:
            cleanup_temp_file(temp_file)

    def test_multiple_objects_single_comment(self):
        """Test detection when multiple objects share a comment block."""
        temp_file = create_temp_python_file("""
            '''Test multiple reservoirs'''
            import cantera as ct

            gas_a = ct.Solution('air.yaml')
            gas_a.TPX = 300, ct.one_atm, 'O2:0.21, N2:0.78, AR:0.01'

            gas_b = ct.Solution('gri30.yaml')
            gas_b.TPX = 300, ct.one_atm, 'CH4:1'

            # Create reservoirs for inlet streams
            # These can be replaced by upstream reactors
            res_a = ct.Reservoir(gas_a, name="Air Reservoir")
            res_b = ct.Reservoir(gas_b, name="Fuel Reservoir")

            # Main mixing reactor
            mixer = ct.IdealGasReactor(gas_b, name="Mixer")

            sim = ct.ReactorNet([mixer])
        """)

        try:
            exec_globals = {}
            with open(temp_file, "r") as f:
                exec(f.read(), exec_globals)

            sim = exec_globals["sim"]
            comments = _smart_extract_object_comments(temp_file, sim)

            # Both reservoirs should get the same comment
            expected_comment = (
                "Create reservoirs for inlet streams\n"
                "These can be replaced by upstream reactors"
            )
            assert "Air Reservoir" in comments
            assert comments["Air Reservoir"] == expected_comment
            assert "Fuel Reservoir" in comments
            assert comments["Fuel Reservoir"] == expected_comment

            # Mixer should get its own comment
            assert "Mixer" in comments
            assert comments["Mixer"] == "Main mixing reactor"

        finally:
            cleanup_temp_file(temp_file)

    def test_flow_devices_detection(self):
        """Test detection of flow devices (MassFlowController, Valve)."""
        temp_file = create_temp_python_file("""
            '''Test flow devices'''
            import cantera as ct

            gas = ct.Solution('gri30.yaml')
            gas.TPX = 300, ct.one_atm, 'CH4:1'

            res1 = ct.Reservoir(gas, name="Source")
            res2 = ct.Reservoir(gas, name="Sink")
            reactor = ct.IdealGasReactor(gas, name="Reactor")

            # Mass flow controller for inlet
            mfc = ct.MassFlowController(res1, reactor, mdot=0.1, name="Inlet MFC")

            # Valve for outlet with pressure control
            valve = ct.Valve(reactor, res2, K=1.0, name="Outlet Valve")

            sim = ct.ReactorNet([reactor])
        """)

        try:
            exec_globals = {}
            with open(temp_file, "r") as f:
                exec(f.read(), exec_globals)

            sim = exec_globals["sim"]
            comments = _smart_extract_object_comments(temp_file, sim)

            assert "Inlet MFC" in comments
            assert comments["Inlet MFC"] == "Mass flow controller for inlet"
            assert "Outlet Valve" in comments
            assert comments["Outlet Valve"] == "Valve for outlet with pressure control"

        finally:
            cleanup_temp_file(temp_file)

    def test_section_comments(self):
        """Test handling of section comments with %% markers."""
        temp_file = create_temp_python_file("""
            '''Test section comments'''
            import cantera as ct

            # %%
            # Reactor setup section
            # Configure the main reactor
            gas = ct.Solution('gri30.yaml')
            reactor = ct.IdealGasReactor(gas, name="Main")

            # %%
            # Flow control section
            # Set up mass flow controllers
            res = ct.Reservoir(gas, name="Source")
            mfc = ct.MassFlowController(res, reactor, name="Controller")

            sim = ct.ReactorNet([reactor])
        """)

        try:
            exec_globals = {}
            with open(temp_file, "r") as f:
                exec(f.read(), exec_globals)

            sim = exec_globals["sim"]
            comments = _smart_extract_object_comments(temp_file, sim)

            assert "Main" in comments
            assert "Reactor setup section" in comments["Main"]
            assert "Configure the main reactor" in comments["Main"]

            assert "Controller" in comments
            assert "Flow control section" in comments["Controller"]
            assert "Set up mass flow controllers" in comments["Controller"]

        finally:
            cleanup_temp_file(temp_file)


class TestSmartDetectionIntegration:
    """Test integration of smart detection with sim2stone conversion."""

    def test_full_conversion_with_comments(self):
        """Test complete conversion from Python to YAML with smart detection."""
        temp_file = create_temp_python_file("""
            '''
            Simple reactor test
            ===================

            A basic reactor network for testing smart detection.
            '''
            import cantera as ct

            # Set up gas solution
            gas = ct.Solution('gri30.yaml')
            gas.TPX = 300, ct.one_atm, 'CH4:1, O2:2, N2:7.52'

            # Create main reactor for combustion
            # This reactor will handle the chemical reactions
            reactor = ct.IdealGasReactor(gas, name="Combustor")

            # Set up inlet reservoir
            inlet_gas = ct.Solution('gri30.yaml')
            inlet_gas.TPX = 300, ct.one_atm, 'CH4:1, O2:2, N2:7.52'
            inlet = ct.Reservoir(inlet_gas, name="Inlet")

            # Mass flow controller for fuel injection
            mfc = ct.MassFlowController(inlet, reactor, mdot=0.1, name="Fuel Injector")

            sim = ct.ReactorNet([reactor])
        """)

        try:
            exec_globals = {}
            with open(temp_file, "r") as f:
                exec(f.read(), exec_globals)

            sim = exec_globals["sim"]

            # Convert to YAML with smart detection
            yaml_content = sim_to_stone_yaml(
                sim, source_file=temp_file, include_comments=True
            )

            # Verify metadata is included
            assert "metadata:" in yaml_content
            assert "title: Converted from" in yaml_content
            assert "Simple reactor test" in yaml_content
            assert (
                "A basic reactor network for testing smart detection." in yaml_content
            )

            # Verify node descriptions
            assert "description: |-" in yaml_content
            assert "Create main reactor for combustion" in yaml_content
            assert "This reactor will handle the chemical reactions" in yaml_content
            assert "Set up inlet reservoir" in yaml_content

            # Verify connection descriptions
            assert "Mass flow controller for fuel injection" in yaml_content

        finally:
            cleanup_temp_file(temp_file)

    def test_no_comments_flag(self):
        """Test that smart detection can be disabled."""
        temp_file = create_temp_python_file("""
            '''Test file with comments'''
            import cantera as ct

            # This comment should be ignored
            gas = ct.Solution('gri30.yaml')
            reactor = ct.IdealGasReactor(gas, name="Test")
            sim = ct.ReactorNet([reactor])
        """)

        try:
            exec_globals = {}
            with open(temp_file, "r") as f:
                exec(f.read(), exec_globals)

            sim = exec_globals["sim"]

            # Convert without comments
            yaml_content = sim_to_stone_yaml(
                sim, source_file=temp_file, include_comments=False
            )

            # Should not contain descriptions
            assert "This comment should be ignored" not in yaml_content
            assert "description:" not in yaml_content

        finally:
            cleanup_temp_file(temp_file)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_file(self):
        """Test handling of empty Python files."""
        temp_file = create_temp_python_file("")

        try:
            metadata = _parse_python_comments(temp_file)
            assert metadata["file_description"] == ""
            assert metadata["variable_comments"] == {}
        finally:
            cleanup_temp_file(temp_file)

    def test_syntax_error_file(self):
        """Test handling of files with syntax errors."""
        temp_file = create_temp_python_file("invalid python syntax !!!")

        try:
            metadata = _parse_python_comments(temp_file)
            # Should not crash, should return empty metadata
            assert isinstance(metadata, dict)
        finally:
            cleanup_temp_file(temp_file)

    def test_no_cantera_objects(self):
        """Test handling of Python files without Cantera objects."""
        temp_file = create_temp_python_file("""
            '''Regular Python file'''

            # Some comment
            x = 42
            y = "hello"

            def func():
                pass
        """)

        try:
            # Create a dummy reactor network
            gas = ct.Solution("gri30.yaml")
            reactor = ct.IdealGasReactor(gas)
            sim = ct.ReactorNet([reactor])

            comments = _smart_extract_object_comments(temp_file, sim)
            # Should not find any relevant comments
            assert len(comments) == 0

        finally:
            cleanup_temp_file(temp_file)

    def test_unicode_comments(self):
        """Test handling of Unicode characters in comments."""
        temp_file = create_temp_python_file("""
            '''Fichier de test avec caractères Unicode'''
            import cantera as ct

            # Réacteur principal avec température élevée
            gas = ct.Solution('gri30.yaml')
            reactor = ct.IdealGasReactor(gas, name="Réacteur")
            sim = ct.ReactorNet([reactor])
        """)

        try:
            exec_globals = {}
            with open(temp_file, "r", encoding="utf-8") as file:
                exec(file.read(), exec_globals)

            sim = exec_globals["sim"]
            comments = _smart_extract_object_comments(temp_file, sim)

            assert "Réacteur" in comments
            assert "température élevée" in comments["Réacteur"]

        finally:
            cleanup_temp_file(temp_file)


if __name__ == "__main__":
    pytest.main([__file__])
