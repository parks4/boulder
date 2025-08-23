from __future__ import annotations

import os
import tempfile
import textwrap

import cantera as ct  # type: ignore

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import (
    load_config_file,
    load_yaml_string_with_comments,
    normalize_config,
    validate_config,
)
from boulder.sim2stone import sim_to_internal_config, sim_to_stone_yaml
from boulder.validation import validate_normalized_config


def _build_test_network():
    """Create a simple network: two reservoirs -> reactor -> reservoir."""
    gas = ct.Solution("gri30.yaml")

    # Upstream reservoirs with different compositions
    gas.TPX = 300.0, ct.one_atm, "O2:0.21, N2:0.78, AR:0.01"
    res_a = ct.Reservoir(gas, name="Air Reservoir")

    gas.TPX = 300.0, ct.one_atm, "CH4:1"
    res_b = ct.Reservoir(gas, name="Fuel Reservoir")

    # Mixer reactor
    gas.TPX = 300.0, ct.one_atm, "O2:0.21, N2:0.78, AR:0.01"
    mixer = ct.IdealGasReactor(gas, name="Mixer")

    # Downstream sink
    downstream = ct.Reservoir(gas, name="Outlet Reservoir")

    # Flow devices
    mfc1 = ct.MassFlowController(
        res_a, mixer, mdot=res_a.thermo.density * 2.5 / 0.21, name="Air Inlet"
    )
    mfc2 = ct.MassFlowController(
        res_b, mixer, mdot=res_b.thermo.density * 1.0, name="Fuel Inlet"
    )
    valve = ct.Valve(mixer, downstream, K=10.0, name="Valve")

    # Only reactors go into ReactorNet (exclude pure reservoirs)
    sim = ct.ReactorNet([mixer])
    return sim, {"mfc1": mfc1, "mfc2": mfc2, "valve": valve}


def test_roundtrip_sim_to_yaml_and_back():
    sim, _ = _build_test_network()

    # Convert sim -> internal config
    internal = sim_to_internal_config(sim, default_mechanism="gri30.yaml")

    # Basic shape checks
    assert (
        len(internal["nodes"]) == 4
    )  # Air Reservoir, Fuel Reservoir, Mixer, Outlet Reservoir
    assert len(internal["connections"]) == 3  # two MFCs + one Valve

    # Serialize to STONE YAML string
    yaml_str = sim_to_stone_yaml(sim, default_mechanism="gri30.yaml")
    loaded_with_comments = load_yaml_string_with_comments(yaml_str)
    normalized = normalize_config(loaded_with_comments)
    validated = validate_config(normalized)

    # Rebuild via CanteraConverter - get mechanism from phases.gas.mechanism (STONE standard)
    phases = validated.get("phases", {})
    gas = phases.get("gas", {}) if isinstance(phases, dict) else {}
    mechanism = gas.get("mechanism", "gri30.yaml")
    converter = DualCanteraConverter(mechanism=mechanism)
    network = converter.build_network(validated)

    # Node parity: same set of reactor IDs
    original_ids = {n["id"] for n in internal["nodes"]}
    rebuilt_ids = set(converter.reactors.keys())
    assert original_ids == rebuilt_ids

    # Connection parity (Flow devices only; Walls would be handled separately)
    original_flow_ids = {
        c["id"]
        for c in internal["connections"]
        if c["type"] in ("MassFlowController", "Valve")
    }
    rebuilt_flow_ids = set(converter.connections.keys())
    assert original_flow_ids == rebuilt_flow_ids

    # ReactorNet parity: one non-reservoir reactor called "Mixer"
    assert len(network.reactors) == 1
    assert network.reactors[0].name == "Mixer"


def test_smart_detection_with_comments():
    """Test sim2stone with smart comment detection enabled."""
    # Create a temporary Python file with comments
    python_content = textwrap.dedent('''
        """
        Test reactor network
        ====================

        A simple test network for validating smart detection.
        """
        import cantera as ct

        # Set up gas solution
        gas = ct.Solution('gri30.yaml')
        gas.TPX = 300.0, ct.one_atm, 'CH4:1, O2:2, N2:7.52'

        # Create main reactor for testing
        # This reactor handles the main reactions
        reactor = ct.IdealGasReactor(gas, name="Test Reactor")

        # Create inlet reservoir
        inlet_gas = ct.Solution('gri30.yaml')
        inlet_gas.TPX = 300.0, ct.one_atm, 'CH4:1, O2:2, N2:7.52'
        inlet = ct.Reservoir(inlet_gas, name="Inlet")

        # Mass flow controller for inlet flow
        mfc = ct.MassFlowController(inlet, reactor, mdot=0.1, name="Inlet MFC")

        sim = ct.ReactorNet([reactor])
    ''')

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(python_content)
        f.flush()
        temp_name = f.name

    try:
        # Execute the Python file to create the network
        exec_globals = {}
        with open(temp_name, "r") as file:
            exec(file.read(), exec_globals)

        sim = exec_globals["sim"]

        # Convert with smart detection enabled
        yaml_str = sim_to_stone_yaml(
            sim,
            default_mechanism="gri30.yaml",
            source_file=temp_name,
            include_comments=True,
        )

        # Verify metadata is included
        assert "metadata:" in yaml_str
        assert "Test reactor network" in yaml_str
        assert "A simple test network for validating smart detection." in yaml_str
        assert f"source_file: {os.path.basename(temp_name)}" in yaml_str

        # Verify node descriptions are included
        assert "description: |-" in yaml_str
        assert "Create main reactor for testing" in yaml_str
        assert "This reactor handles the main reactions" in yaml_str
        assert "Create inlet reservoir" in yaml_str

        # Verify connection descriptions are included
        assert "Mass flow controller for inlet flow" in yaml_str

        # Verify the YAML can be loaded and validated
        loaded = load_yaml_string_with_comments(yaml_str)
        normalized = normalize_config(loaded)
        validated = validate_config(normalized)

        # Should have metadata section
        assert "metadata" in validated
        assert (
            validated["metadata"]["title"]
            == f"Converted from {os.path.basename(temp_name)}"
        )

    finally:
        try:
            os.unlink(temp_name)
        except (OSError, PermissionError):
            pass  # Ignore cleanup errors on Windows


def test_smart_detection_disabled():
    """Test sim2stone with smart comment detection disabled."""
    # Create a temporary Python file with comments
    python_content = textwrap.dedent('''
        """This docstring should be ignored"""
        import cantera as ct

        # This comment should be ignored
        gas = ct.Solution('gri30.yaml')
        reactor = ct.IdealGasReactor(gas, name="Test")
        sim = ct.ReactorNet([reactor])
    ''')

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(python_content)
        f.flush()
        temp_name = f.name

    try:
        # Execute the Python file to create the network
        exec_globals = {}
        with open(temp_name, "r") as file:
            exec(file.read(), exec_globals)

        sim = exec_globals["sim"]

        # Convert with smart detection disabled
        yaml_str = sim_to_stone_yaml(
            sim,
            default_mechanism="gri30.yaml",
            source_file=temp_name,
            include_comments=False,
        )

        # Should not contain comments or descriptions
        assert "This docstring should be ignored" not in yaml_str
        assert "This comment should be ignored" not in yaml_str
        assert "description:" not in yaml_str
        assert "metadata:" not in yaml_str or "description:" not in yaml_str

    finally:
        try:
            os.unlink(temp_name)
        except (OSError, PermissionError):
            pass  # Ignore cleanup errors on Windows


def test_smart_detection_no_source_file():
    """Test sim2stone when no source file is provided."""
    sim, _ = _build_test_network()

    # Convert without source file
    yaml_str = sim_to_stone_yaml(
        sim, default_mechanism="gri30.yaml", source_file=None, include_comments=True
    )

    # Should not contain descriptions from smart detection
    # (but may contain basic metadata)
    assert "Create main reactor" not in yaml_str
    assert "Mass flow controller" not in yaml_str


def test_sim2stone_yaml_validation():
    """Test that sim2stone generated YAML passes Boulder config validation."""
    sim, _ = _build_test_network()

    # Generate YAML with sim2stone
    yaml_str = sim_to_stone_yaml(sim, default_mechanism="gri30.yaml")

    # Test that the generated YAML can be loaded
    loaded = load_yaml_string_with_comments(yaml_str)
    assert loaded is not None

    # Test that it passes normalization
    normalized = normalize_config(loaded)
    assert normalized is not None

    # Test that it passes Boulder's validation
    validate_normalized_config(normalized)  # Should not raise

    # Test that it passes the legacy validate_config as well
    validated = validate_config(normalized)
    assert validated is not None


def test_sim2stone_yaml_validation_with_comments():
    """Test that sim2stone generated YAML with comments passes validation."""
    # Create a temporary Python file with comments
    python_content = textwrap.dedent('''
        """
        Test validation network
        =======================

        A network designed to test YAML validation with comments.
        """
        import cantera as ct

        # Main gas solution
        gas = ct.Solution('gri30.yaml')
        gas.TPX = 300.0, ct.one_atm, 'CH4:1, O2:2, N2:7.52'

        # Primary reactor for validation testing
        reactor = ct.IdealGasReactor(gas, name="Validation Reactor")

        # Inlet reservoir for testing
        inlet_gas = ct.Solution('gri30.yaml')
        inlet_gas.TPX = 300.0, ct.one_atm, 'CH4:1'
        inlet = ct.Reservoir(inlet_gas, name="Test Inlet")

        # Flow controller for validation
        mfc = ct.MassFlowController(inlet, reactor, mdot=0.05, name="Test MFC")

        sim = ct.ReactorNet([reactor])
    ''')

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(python_content)
        f.flush()
        temp_name = f.name

    try:
        # Execute the Python file to create the network
        exec_globals = {}
        with open(temp_name, "r") as file:
            exec(file.read(), exec_globals)

        sim = exec_globals["sim"]

        # Generate YAML with comments using sim2stone
        yaml_str = sim_to_stone_yaml(
            sim,
            default_mechanism="gri30.yaml",
            source_file=temp_name,
            include_comments=True,
        )

        # Test that the generated YAML can be loaded
        loaded = load_yaml_string_with_comments(yaml_str)
        assert loaded is not None

        # Test that it passes normalization
        normalized = normalize_config(loaded)
        assert normalized is not None

        # Test that it passes Boulder's validation
        validate_normalized_config(normalized)  # Should not raise

        # Test that it passes the legacy validate_config as well
        validated = validate_config(normalized)
        assert validated is not None

        # Verify metadata is preserved through validation
        assert "metadata" in validated
        assert "title" in validated["metadata"]
        assert "description" in validated["metadata"]

    finally:
        try:
            os.unlink(temp_name)
        except (OSError, PermissionError):
            pass  # Ignore cleanup errors on Windows


def test_sim2stone_yaml_format_compliance():
    """Test that sim2stone generated YAML is compatible with pre-commit formatting."""
    import subprocess
    import sys

    sim, _ = _build_test_network()

    # Generate YAML with sim2stone
    yaml_str = sim_to_stone_yaml(sim, default_mechanism="gri30.yaml")

    # Write to a temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        f.flush()
        temp_name = f.name

    try:
        # Test that the YAML passes check-yaml hook
        result = subprocess.run(
            [sys.executable, "-m", "pre_commit", "run", "check-yaml", "--files", temp_name],
            capture_output=True,
            text=True,
        )
        # Note: pre-commit may not be available in all test environments
        # so we'll make this test conditional
        if result.returncode == 0 or "command not found" in result.stderr.lower():
            # Either passed or pre-commit not available - both are acceptable
            pass
        else:
            pytest.fail(f"Generated YAML failed check-yaml validation: {result.stderr}")

        # Test that the YAML can be loaded by PyYAML (basic syntax check)
        import yaml
        with open(temp_name, "r") as f:
            parsed = yaml.safe_load(f)
        assert parsed is not None

    finally:
        try:
            os.unlink(temp_name)
        except (OSError, PermissionError):
            pass  # Ignore cleanup errors on Windows


def test_mix1_example_yaml_validation():
    """Test that examples/mix1.py -> mix1.yaml conversion passes validation."""
    import sys
    from pathlib import Path

    # Get the path to examples/mix1.py
    examples_dir = Path(__file__).parent.parent / "examples"
    mix1_path = examples_dir / "mix1.py"

    if not mix1_path.exists():
        pytest.skip("examples/mix1.py not found")

    # Import and execute mix1.py to get the simulation
    sys.path.insert(0, str(examples_dir))
    try:
        import mix1
        sim = mix1.sim
    except ImportError:
        pytest.skip("Could not import mix1 example")
    finally:
        # Clean up sys.path
        if str(examples_dir) in sys.path:
            sys.path.remove(str(examples_dir))

    # Generate YAML using sim2stone with smart detection
    yaml_str = sim_to_stone_yaml(
        sim,
        default_mechanism="gri30.yaml",
        source_file=str(mix1_path),
        include_comments=True,
    )

    # Test that the generated YAML can be loaded
    loaded = load_yaml_string_with_comments(yaml_str)
    assert loaded is not None

    # Test that it passes normalization
    normalized = normalize_config(loaded)
    assert normalized is not None

    # Test that it passes Boulder's validation
    validate_normalized_config(normalized)  # Should not raise

    # Test that it passes the legacy validate_config as well
    validated = validate_config(normalized)
    assert validated is not None

    # Verify expected structure
    assert "nodes" in validated
    assert "connections" in validated
    assert len(validated["nodes"]) >= 3  # Should have multiple reactors/reservoirs
    assert len(validated["connections"]) >= 2  # Should have multiple connections

    # Verify metadata is included when using smart detection
    assert "metadata" in validated
    assert "title" in validated["metadata"]
    assert "description" in validated["metadata"]
    assert "source_file" in validated["metadata"]
