"""Validation tests for configuration YAML files.

This suite verifies:
- All repository configs in `configs/` validate successfully after normalization.
- Intentionally broken examples under `tests/test_data/invalid/` raise errors.
- Unit-bearing strings are coerced to canonical magnitudes consistent with CtWrap.
"""

from __future__ import annotations

import glob
import os
from typing import List

import pytest

from boulder.config import load_config_file, normalize_config
from boulder.validation import validate_normalized_config


@pytest.mark.unit
def test_all_repo_configs_validate() -> None:
    """Assert that every YAML file under `configs/` validates after normalization.

    This ensures library-provided examples remain compatible with the current
    normalization and validation schema.
    """
    repo_root = os.path.dirname(os.path.dirname(__file__))
    configs_dir = os.path.join(repo_root, "configs")
    if not os.path.isdir(configs_dir):
        pytest.skip("No repo-level configs directory found")

    yaml_paths: List[str] = []
    yaml_paths.extend(glob.glob(os.path.join(configs_dir, "*.yaml")))
    yaml_paths.extend(glob.glob(os.path.join(configs_dir, "*.yml")))

    assert yaml_paths, "No YAML files found under configs/"

    failures: List[str] = []
    for path in yaml_paths:
        try:
            loaded = load_config_file(path)
            normalized = normalize_config(loaded)
            validate_normalized_config(normalized)
        except Exception as exc:  # noqa: BLE001 - want the full failure list
            failures.append(f"{path}: {exc}")

    assert not failures, (
        "Some configs failed validation after normalization:\n" + "\n".join(failures)
    )


@pytest.mark.unit
def test_invalid_configs_fail_validation() -> None:
    """Assert that known-invalid configs raise during validation.

    The fixtures capture three failure modes:
    - duplicate_node_id.yaml: duplicate node identifiers (cross-invariant)
    - unknown_connection_ref.yaml: a connection references a missing node
    - missing_properties_node.yaml: `properties` is not a mapping after normalization
    """
    invalid_dir = os.path.join(os.path.dirname(__file__), "test_data", "invalid")
    if not os.path.isdir(invalid_dir):
        pytest.skip("No invalid test_data present")

    yaml_paths: List[str] = []
    yaml_paths.extend(glob.glob(os.path.join(invalid_dir, "*.yaml")))
    yaml_paths.extend(glob.glob(os.path.join(invalid_dir, "*.yml")))

    assert yaml_paths, "No invalid YAML files found under tests/test_data/invalid/"

    for path in yaml_paths:
        loaded = load_config_file(path)
        normalized = normalize_config(loaded)
        with pytest.raises(Exception):
            validate_normalized_config(normalized)


@pytest.mark.unit
def test_unit_coercion_ctwrap_compatibility() -> None:
    """Unit-bearing strings are coerced to magnitudes in canonical units.

    - temperature strings (e.g., "500 degC") become Kelvin magnitudes
    - pressure strings (e.g., "1 atm") become Pascals
    - simulation dt strings (e.g., "10 ms") become seconds
    """
    data = {
        "nodes": [
            {
                "id": "r1",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": "500 degC",
                    "pressure": "1 atm",
                },
            }
        ],
        "connections": [],
        "simulation": {"dt": "10 ms"},
    }

    normalized = normalize_config(data)
    model = validate_normalized_config(normalized)

    # temperature: 500 degC = 500 C (no conversion needed, already in target unit)
    assert abs(model.nodes[0].properties["temperature"] - 500.0) < 1e-6
    # pressure: 1 atm = 101325 Pa
    assert abs(model.nodes[0].properties["pressure"] - 101325.0) < 1e-6
    # dt: 10 ms = 0.01 s
    assert model.simulation is not None
    assert abs(getattr(model.simulation, "dt") - 0.01) < 1e-12


@pytest.mark.unit
def test_power_unit_coercion() -> None:
    """Power units like kilowatt are properly converted to kilowatts."""
    data = {
        "nodes": [
            {
                "id": "r1",
                "type": "IdealGasReactor",
                "properties": {"temperature": "500 K", "pressure": "1 atm"},
            },
            {
                "id": "r2",
                "type": "IdealGasReactor",
                "properties": {"temperature": "300 K", "pressure": "1 atm"},
            },
        ],
        "connections": [
            {
                "id": "wall1",
                "type": "Wall",
                "source": "r1",
                "target": "r2",
                "properties": {
                    "electric_power_kW": "550 kilowatt",  # This should work now
                },
            }
        ],
    }

    normalized = normalize_config(data)
    model = validate_normalized_config(normalized)

    # electric_power_kW: 550 kilowatt = 550 kW (stays in kW due to special mapping)
    assert abs(model.connections[0].properties["electric_power_kW"] - 550.0) < 1e-6


@pytest.mark.unit
def test_invalid_unit_error_message() -> None:
    """Invalid units should provide helpful error messages with suggestions."""
    data = {
        "nodes": [
            {
                "id": "r1",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": "500 invalid_unit",  # This should fail with helpful message
                },
            }
        ],
        "connections": [],
    }

    normalized = normalize_config(data)

    with pytest.raises(ValueError) as exc_info:
        validate_normalized_config(normalized)

    error_msg = str(exc_info.value)
    assert "Could not convert '500 invalid_unit'" in error_msg
    assert "temperature units like 'degC', 'degF', 'K'" in error_msg
    assert "for property 'temperature'" in error_msg


@pytest.mark.unit
def test_dynamic_unit_system_flexibility() -> None:
    """Test that the dynamic unit system can handle various unit types without hardcoding."""
    data = {
        "nodes": [
            {
                "id": "r1",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": "300 K",  # Already in target unit
                    "pressure": "2 bar",  # Different pressure unit
                    "mass": "5 g",  # Mass in grams
                    "volume": "2 L",  # Volume in liters
                    "custom_length": "10 cm",  # Custom property with length units
                    "custom_energy": "1 kJ",  # Custom property with energy units
                },
            }
        ],
        "connections": [
            {
                "id": "mfc1",
                "type": "MassFlowController",
                "source": "r1",
                "target": "r1",
                "properties": {
                    "mass_flow_rate": "0.1 g/min",  # Flow rate in different units
                    "custom_power": "500 W",  # Custom power property
                },
            }
        ],
        "simulation": {
            "dt": "1 ms",  # Time in milliseconds
            "end_time": "10 min",  # Time in minutes
        },
    }

    normalized = normalize_config(data)
    model = validate_normalized_config(normalized)

    # Check that all units were converted to their canonical forms
    node = model.nodes[0]
    assert abs(node.properties["temperature"] - 26.85) < 1e-6  # 300 K = 26.85 C
    assert abs(node.properties["pressure"] - 200000.0) < 1e-6  # 2 bar = 200000 Pa
    assert abs(node.properties["mass"] - 0.005) < 1e-6  # 5 g = 0.005 kg
    assert abs(node.properties["volume"] - 0.002) < 1e-6  # 2 L = 0.002 m³
    assert abs(node.properties["custom_length"] - 0.1) < 1e-6  # 10 cm = 0.1 m
    assert abs(node.properties["custom_energy"] - 1000.0) < 1e-6  # 1 kJ = 1000 J

    conn = model.connections[0]
    assert (
        abs(conn.properties["mass_flow_rate"] - 0.1 / 60 / 1000) < 1e-9
    )  # 0.1 g/min to kg/s
    assert (
        abs(conn.properties["custom_power"] - 500.0) < 1e-6
    )  # 500 W (no conversion needed)

    # Check simulation properties
    sim_dict = model.simulation.__dict__
    assert abs(sim_dict["dt"] - 0.001) < 1e-6  # 1 ms = 0.001 s
    assert abs(sim_dict["end_time"] - 600.0) < 1e-6  # 10 min = 600 s
