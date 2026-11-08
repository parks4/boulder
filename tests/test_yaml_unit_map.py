"""Tests for boulder/yaml_unit_map.py.

Covers build_unit_map and apply_unit_map_inplace: unit-bearing scalar
detection, verbatim preservation when unchanged, Pint inverse conversion
when values differ, and correct handling of offset units (degC/degF).
"""

import math

import pytest

from boulder.config import load_yaml_string_with_comments
from boulder.yaml_unit_map import apply_unit_map_inplace, build_unit_map

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(yaml_str: str):
    return load_yaml_string_with_comments(yaml_str)


def _dump(tree) -> str:
    from boulder.config import yaml_to_string_with_comments

    return yaml_to_string_with_comments(tree)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildUnitMap:
    def test_records_temperature_pressure_flow(self):
        """Asserts that temperature, pressure, and mass_flow_rate with unit strings.

        Temperature, pressure, and mass_flow_rate with unit strings are all recorded
        in the unit_map with correct original text and SI value.

        Checks:
        - ("inlet", ("Reservoir", "temperature")) -> text "298.15 K", si ~298.15
        - ("inlet", ("Reservoir", "pressure")) -> text "1 atm", si ~101325
        - ("feed_to_pfr", ("MassFlowController", "mass_flow_rate")) -> text "10 kg/h",
          si ~0.002777...
        """
        yaml = (
            "network:\n"
            "  - id: inlet\n"
            "    Reservoir:\n"
            "      temperature: 298.15 K\n"
            "      pressure: 1 atm\n"
            "  - id: feed_to_pfr\n"
            "    MassFlowController:\n"
            "      mass_flow_rate: 10 kg/h\n"
            "    source: inlet\n"
            "    target: pfr\n"
        )
        tree = _load(yaml)
        umap = build_unit_map(tree)

        temp_key = ("inlet", ("Reservoir", "temperature"))
        assert temp_key in umap, "temperature entry missing"
        orig_text, _, si_val, _ = umap[temp_key]
        assert orig_text == "298.15 K"
        assert math.isclose(si_val, 298.15, rel_tol=1e-6)

        press_key = ("inlet", ("Reservoir", "pressure"))
        assert press_key in umap, "pressure entry missing"
        orig_text, _, si_val, _ = umap[press_key]
        assert orig_text == "1 atm"
        assert math.isclose(si_val, 101325.0, rel_tol=1e-3)

        flow_key = ("feed_to_pfr", ("MassFlowController", "mass_flow_rate"))
        assert flow_key in umap, "mass_flow_rate entry missing"
        orig_text, _, si_val, _ = umap[flow_key]
        assert orig_text == "10 kg/h"
        assert math.isclose(si_val, 10 / 3600, rel_tol=1e-6)

    def test_ignores_bare_numbers(self):
        """Asserts that plain numeric values (no unit string) are not recorded.

        temperature: 300.0 with no unit should not appear in the unit_map.
        """
        yaml = (
            "network:\n"
            "  - id: r1\n"
            "    Reservoir:\n"
            "      temperature: 300.0\n"
            "      pressure: 101325\n"
        )
        tree = _load(yaml)
        umap = build_unit_map(tree)
        assert ("r1", ("Reservoir", "temperature")) not in umap
        assert ("r1", ("Reservoir", "pressure")) not in umap

    def test_ignores_non_unit_strings(self):
        """Asserts that plain string values like composition are not recorded."""
        yaml = 'network:\n  - id: r1\n    Reservoir:\n      composition: "CH4:1"\n'
        tree = _load(yaml)
        umap = build_unit_map(tree)
        assert len(umap) == 0


class TestApplyUnitMapInplace:
    def test_preserves_unchanged_value_verbatim(self):
        """Asserts verbatim restoration when SI value matches the original.

        When the SI value matches the original, the original text is restored
        verbatim (no reformatting of scientific notation etc.).

        Original: pressure: 1 atm (SI = 101325 Pa). Config pressure = 101325.
        Output YAML must contain '1 atm'.
        """
        yaml = "network:\n  - id: inlet\n    Reservoir:\n      pressure: 1 atm\n"
        tree = _load(yaml)
        umap = build_unit_map(tree)
        config = {
            "nodes": [
                {
                    "id": "inlet",
                    "type": "Reservoir",
                    "properties": {"pressure": 101325.0},
                }
            ],
            "connections": [],
        }
        warnings = apply_unit_map_inplace(tree, umap, config)
        out = _dump(tree)
        assert "1 atm" in out
        assert warnings == []

    def test_converts_changed_pressure_to_original_unit(self):
        """Asserts doubled pressure is written in original units.

        Pressure doubled from 1 atm to 2 atm (202650 Pa in config) is written as
        '2 atm' in the merged YAML, not as a bare SI float.
        """
        yaml = "network:\n  - id: inlet\n    Reservoir:\n      pressure: 1 atm\n"
        tree = _load(yaml)
        umap = build_unit_map(tree)
        config = {
            "nodes": [
                {
                    "id": "inlet",
                    "type": "Reservoir",
                    "properties": {"pressure": 202650.0},
                }
            ],
            "connections": [],
        }
        apply_unit_map_inplace(tree, umap, config)
        out = _dump(tree)
        assert "2 atm" in out
        assert "202650" not in out

    def test_handles_kg_per_hour(self):
        """Asserts mass_flow_rate with unit kg/h round-trips correctly.

        Original 10 kg/h changed to 5 kg/h (half the SI value).

        Output must contain '5 kg/h' (or equivalent with :g formatting).
        """
        yaml = (
            "network:\n"
            "  - id: mfc\n"
            "    MassFlowController:\n"
            "      mass_flow_rate: 10 kg/h\n"
            "    source: a\n"
            "    target: b\n"
        )
        tree = _load(yaml)
        umap = build_unit_map(tree)
        half_si = 5 / 3600  # 5 kg/h in kg/s
        config = {
            "nodes": [],
            "connections": [
                {
                    "id": "mfc",
                    "type": "MassFlowController",
                    "source": "a",
                    "target": "b",
                    "properties": {"mass_flow_rate": half_si},
                }
            ],
        }
        apply_unit_map_inplace(tree, umap, config)
        out = _dump(tree)
        assert "kg/h" in out
        assert "5" in out

    def test_handles_celsius_without_offset_error(self):
        """Asserts degC temperatures round-trip without Pint offset errors.

        Temperature in degC round-trips correctly without raising
        Pint's OffsetUnitCalculusError.

        Original: 500 degC (773.15 K). Config changed to 673.15 K (400 degC).
        Output must contain '400' and 'degC'; no exception raised.
        """
        yaml = "network:\n  - id: r1\n    Reservoir:\n      temperature: 500 degC\n"
        tree = _load(yaml)
        umap = build_unit_map(tree)
        config = {
            "nodes": [
                {"id": "r1", "type": "Reservoir", "properties": {"temperature": 673.15}}
            ],  # 400 °C
            "connections": [],
        }
        warnings = apply_unit_map_inplace(tree, umap, config)
        out = _dump(tree)
        assert "degC" in out
        assert "400" in out
        assert warnings == []

    def test_emits_warning_on_pint_failure_and_leaves_si(self):
        """Asserts malformed units yield a warning and leave SI scalars.

        When Pint cannot back-convert (malformed unit 'xyzzy'), a warning string is
        returned and the scalar is left as a bare SI float.
        """
        from boulder.yaml_unit_map import UnitMap

        yaml = "network:\n  - id: r1\n    Reservoir:\n      pressure: 1 atm\n"
        tree = _load(yaml)
        # Inject a fake unit_map entry with a bad unit that Pint can't use.
        umap: UnitMap = {
            ("r1", ("Reservoir", "pressure")): ("1 xyzzy", "xyzzy", 101325.0, str),
        }
        config = {
            "nodes": [
                {"id": "r1", "type": "Reservoir", "properties": {"pressure": 202650.0}}
            ],
            "connections": [],
        }
        warnings = apply_unit_map_inplace(tree, umap, config)
        assert len(warnings) == 1
        assert "xyzzy" in warnings[0] or "back-conversion" in warnings[0].lower()


_SCENARIO_OVERLAY_YAML = """\
metadata:
  stone_version: "2.2"
phases:
  gas:
    mechanism: gri30.yaml
stages:
  first:
    mechanism: gri30.yaml
    solve: advance
    advance_time: 1.0e-3
  second:
    mechanism: gri30.yaml
    solve: advance
    advance_time: 1.0e-3
first:
- id: feed
  Reservoir:
    temperature: 300 K
    pressure: 101325 Pa
    composition: "CH4:1,O2:2,N2:7.52"
- id: reactor
  IdealGasConstPressureMoleReactor:
    volume: 1.0e-5 m**3
- id: feed_to_reactor
  MassFlowController:
    mass_flow_rate: 1.0e-4 kg/s
  source: feed
  target: reactor
second:
- id: cell
  IdealGasConstPressureMoleReactor:
    volume: 2.5e-6 m**3
- id: reactor_to_cell
  source: reactor
  target: cell
  mass_flow_rate: 1.0e-4 kg/s
- id: outlet
  OutletSink:
    pressure: 101325 Pa
- id: cell_to_outlet
  MassFlowController:
    mass_flow_rate: 1.0e-4 kg/s
  source: cell
  target: outlet
scenarios:
  low_p:
    second:
    - id: outlet
      OutletSink:
        pressure: 0.3 bar
"""


class TestScenarioOverlaysSurviveSync:
    @pytest.mark.parametrize(
        "validated", [True, False], ids=["validated", "normalized"]
    )
    def test_unchanged_round_trip_keeps_scenario_and_base_values(self, validated):
        """Asserts a sync of the unchanged config leaves ``scenarios:`` untouched.

        A scenario overlay sets ``pressure`` on node ``outlet``, which also
        exists in the base network. After ``merge_config_into_yaml`` on the
        unchanged config:

        * the scenario keeps ``0.3 bar`` (it must not take the base value);
        * the base node keeps ``101325 Pa`` (it must not take the scenario unit).

        Checked for a validated config (no ``scenarios`` key) and for a merely
        normalized one, which still carries the overlays in SI.
        """
        import yaml

        from boulder.config import (
            merge_config_into_yaml,
            normalize_config,
            validate_config,
        )

        config = normalize_config(yaml.safe_load(_SCENARIO_OVERLAY_YAML))
        if validated:
            config = validate_config(config)
        merged_yaml, _ = merge_config_into_yaml(config, _SCENARIO_OVERLAY_YAML)
        merged = load_yaml_string_with_comments(merged_yaml)

        overlay = merged["scenarios"]["low_p"]["second"][0]
        assert overlay["OutletSink"]["pressure"] == "0.3 bar"
        base = next(item for item in merged["second"] if item["id"] == "outlet")
        assert base["OutletSink"]["pressure"] == "101325 Pa"
