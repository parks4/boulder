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

    # temperature: 500 degC = 773.15 K
    assert abs(model.nodes[0].properties["temperature"] - 773.15) < 1e-6
    # pressure: 1 atm = 101325 Pa
    assert abs(model.nodes[0].properties["pressure"] - 101325.0) < 1e-6
    # dt: 10 ms = 0.01 s
    assert model.simulation is not None
    assert abs(getattr(model.simulation, "dt") - 0.01) < 1e-12
