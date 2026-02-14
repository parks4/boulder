"""Schema and validation utilities for normalized configuration.

This module defines Pydantic models for Boulder internal (normalized) config and exposes a
`validate_normalized_config` function that validates dictionaries after `normalize_config`.

Validation is schema-only and does not build or inspect any simulation network.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from pint import UnitRegistry
from pydantic import BaseModel, Field, validator

# Unit suggestions for error messages
UNIT_SUGGESTIONS = {
    "celsius": "temperature units like 'degC', 'degF', 'K'",
    "kelvin": "temperature units like 'degC', 'degF', 'K'",
    "pascal": "pressure units like 'atm', 'bar', 'Pa', 'psi'",
    "kilogram": "mass units like 'kg', 'g', 'lb'",
    "meter**3": "volume units like 'm3', 'L', 'mL', 'ft3'",
    "kilogram/second": "flow rate units like 'kg/s', 'g/min', 'lb/hr'",
    "second": "time units like 's', 'ms', 'min', 'hr'",
    "watt": "power units like 'W', 'kW', 'MW', 'hp'",
    "kilowatt": "power units like 'kW', 'W', 'MW', 'hp'",
    "joule": "energy units like 'J', 'kJ', 'cal', 'BTU'",
    "meter": "length units like 'm', 'cm', 'ft', 'in'",
}


class PhasesModel(BaseModel):
    """Phases section of the STONE config (chemistry/phase configuration)."""

    class Config:
        extra = "allow"  # Allow arbitrary phase types


class SettingsModel(BaseModel):
    """Settings section of the STONE config (simulation-level settings)."""

    class Config:
        extra = "allow"  # Allow arbitrary settings


class NodeModel(BaseModel):
    """Node entry in `nodes` list of normalized config."""

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    properties: Dict[str, Any] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = None

    @validator("properties")
    def ensure_properties_is_object(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("node.properties must be a mapping/dict")
        return value


class ConnectionModel(BaseModel):
    """Connection entry in `connections` list of normalized config."""

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    properties: Dict[str, Any] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = None

    @validator("properties")
    def ensure_properties_is_object(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("connection.properties must be a mapping/dict")
        return value


class NormalizedConfigModel(BaseModel):
    """Top-level normalized configuration model."""

    metadata: Optional[Dict[str, Any]] = None
    phases: Optional[PhasesModel] = None
    settings: Optional[SettingsModel] = None
    nodes: List[NodeModel]
    connections: List[ConnectionModel] = Field(default_factory=list)
    # Preserve top-level `output` block (flexible shape). Validation of its content
    # is handled by feature-specific parsers; we just carry it through here.
    output: Optional[Any] = None

    def __init__(self, **data):
        super().__init__(**data)
        self._validate_references_and_uniqueness()
        self._coerce_units()

    def _validate_references_and_uniqueness(self) -> None:
        node_ids: List[str] = [n.id for n in self.nodes]

        # Unique node IDs
        seen_nodes: Set[str] = set()
        for nid in node_ids:
            if nid in seen_nodes:
                raise ValueError(f"Duplicate node id detected: '{nid}'")
            seen_nodes.add(nid)

        # Unique connection IDs
        seen_conns: Set[str] = set()
        for conn in self.connections:
            if conn.id in seen_conns:
                raise ValueError(f"Duplicate connection id detected: '{conn.id}'")
            seen_conns.add(conn.id)

        # Source/target references must exist
        valid_nodes: Set[str] = set(node_ids)
        for conn in self.connections:
            if conn.source not in valid_nodes:
                raise ValueError(
                    f"Connection '{conn.id}' source '{conn.source}' does not reference an existing node"
                )
            if conn.target not in valid_nodes:
                raise ValueError(
                    f"Connection '{conn.id}' target '{conn.target}' does not reference an existing node"
                )

    def _coerce_units(self) -> None:
        """Coerce unit-bearing strings to canonical units using pint.

        Mirrors ctwrap behavior: values defined as strings with units are converted
        to base magnitudes in consistent units. Unknown keys remain unchanged.

        This uses dynamic unit detection based on property names and pint's capabilities.
        """
        unit_registry: UnitRegistry = UnitRegistry()

        # Define preferred target units for common physical quantities
        # This maps dimensionalities to preferred units, not property names to units
        preferred_units = {
            "[temperature]": "celsius",
            "[mass] / [length] / [time] ** 2": "pascal",  # pressure
            "[mass]": "kilogram",
            "[length] ** 3": "meter**3",  # volume
            "[mass] / [time]": "kilogram/second",  # mass flow rate
            "[time]": "second",
            "[mass] * [length] ** 2 / [time] ** 3": "watt",  # power
            "[mass] * [length] ** 2 / [time] ** 2": "joule",  # energy
            "[length]": "meter",
        }

        # Special cases for property names that need specific handling
        special_property_mappings = {
            "electric_power_kW": "kilowatt",  # Keep in kW for backward compatibility
        }

        def _get_target_unit_for_property(
            property_name: str, val: str
        ) -> Optional[str]:
            """Determine the target unit for a property based on its value and name."""
            # Check special mappings first
            if property_name in special_property_mappings:
                return special_property_mappings[property_name]

            # Property name-based hints for common properties
            property_hints = {
                "temperature": "celsius",
                "pressure": "pascal",
                "mass": "kilogram",
                "volume": "meter**3",
                "time": "second",
                "dt": "second",
                "end_time": "second",
                "max_time": "second",
            }

            # Check if property name suggests a unit type
            if property_name in property_hints:
                return property_hints[property_name]

            # Special handling for temperature strings (they fail in pint due to offset units)
            import re

            if re.search(r"\b(degc|celsius|degf|fahrenheit|k|kelvin)\b", val.lower()):
                return "celsius"  # Changed to match the preferred unit

            try:
                # Parse the value to determine its dimensionality
                qty: Any = unit_registry.Quantity(val)
                dimensionality_str = str(qty.dimensionality)

                # Look up preferred unit for this dimensionality
                return preferred_units.get(dimensionality_str)
            except Exception:
                return None

        def _coerce_value(val: Any, property_name: str = "") -> Any:
            if isinstance(val, str):
                try:
                    # First, determine what unit we should convert to
                    target_unit = _get_target_unit_for_property(property_name, val)
                    if not target_unit:
                        # If we can't determine a target unit, return as-is
                        return val

                    # Special handling for temperature conversion (offset units)
                    if target_unit in ["kelvin", "celsius"]:
                        import re

                        match = re.match(
                            r"([+-]?\d*\.?\d+)\s*([a-zA-Z°]+(?:[ -]?[a-zA-Z]+)*)",
                            val.strip(),
                        )
                        if match:
                            value, temp_unit = match.groups()
                            try:
                                value = float(value)
                            except ValueError:
                                raise ValueError(
                                    f"Could not convert '{value}' to a float for property '{property_name}'. "
                                    "Please ensure the value is a valid number followed by a "
                                    "temperature unit, e.g. '25 degC', '77 degF', or '298 K'."
                                )
                            temp_unit = temp_unit.lower()

                            # Convert to target temperature unit
                            if target_unit == "kelvin":
                                # Convert to Kelvin
                                if temp_unit in ["degc", "celsius", "c"]:
                                    return value + 273.15
                                elif temp_unit in ["degf", "fahrenheit", "f"]:
                                    return (value - 32) * 5 / 9 + 273.15
                                elif temp_unit in ["k", "kelvin"]:
                                    return value
                            elif target_unit == "celsius":
                                # Convert to Celsius
                                if temp_unit in ["degc", "celsius", "c"]:
                                    return value
                                elif temp_unit in ["degf", "fahrenheit", "f"]:
                                    return (value - 32) * 5 / 9
                                elif temp_unit in ["k", "kelvin"]:
                                    return value - 273.15

                    # Use pint for all other conversions
                    qty: Any = unit_registry.Quantity(val)
                    return qty.to(target_unit).magnitude

                except Exception as e:
                    # Provide helpful error message with suggested units
                    # First try to get suggestions based on target unit
                    if target_unit:
                        suggestion = UNIT_SUGGESTIONS.get(
                            target_unit, f"units compatible with {target_unit}"
                        )
                    else:
                        # Try to get suggestions based on dimensionality
                        try:
                            qty = unit_registry.Quantity(val)
                            dimensionality = str(qty.dimensionality)

                            suggestions_by_dim = {
                                "[temperature]": "temperature units like 'degC', 'degF', 'K'",
                                "[mass] / [length] / [time] ** 2": (
                                    "pressure units like 'atm', 'bar', 'Pa', 'psi'"
                                ),
                                "[mass]": "mass units like 'kg', 'g', 'lb'",
                                "[length] ** 3": "volume units like 'm**3', 'L', 'mL', 'ft**3'",
                                "[mass] / [time]": "flow rate units like 'kg/s', 'g/min', 'lb/hr'",
                                "[time]": "time units like 's', 'ms', 'min', 'hr'",
                                "[mass] * [length] ** 2 / [time] ** 3": (
                                    "power units like 'kW', 'W', 'MW', 'hp'"
                                ),
                                "[mass] * [length] ** 2 / [time] ** 2": (
                                    "energy units like 'J', 'kJ', 'cal', 'BTU'"
                                ),
                                "[length]": "length units like 'm', 'cm', 'ft', 'in'",
                            }
                            suggestion = suggestions_by_dim.get(
                                dimensionality,
                                f"units with dimensionality {dimensionality}",
                            )
                        except Exception:
                            suggestion = "valid units"

                    prop_info = (
                        f" for property '{property_name}'" if property_name else ""
                    )
                    raise ValueError(
                        f"Could not convert '{val}'{prop_info}. "
                        f"Please use {suggestion}. "
                        f"Original error: {str(e)}"
                    )
            return val

        # Process all properties in nodes dynamically
        for node in self.nodes:
            for key, value in node.properties.items():
                node.properties[key] = _coerce_value(value, key)

        # Process all properties in connections dynamically
        for conn in self.connections:
            for key, value in conn.properties.items():
                conn.properties[key] = _coerce_value(value, key)

        # Process settings properties dynamically
        if isinstance(self.settings, SettingsModel):
            # For settings, we need to handle it differently since it's a Pydantic model
            # with extra fields allowed. In Pydantic v1, extra fields are stored in __fields_set__
            # and accessible via dict() method or direct attribute access.

            # Get all the settings data as a dict
            settings_data = (
                self.settings.dict()
                if hasattr(self.settings, "dict")
                else self.settings.__dict__
            )

            # Process each field and mirror updates into __dict__ for compatibility
            coerced_updates: Dict[str, Any] = {}
            for key, value in settings_data.items():
                if isinstance(value, str):
                    coerced = _coerce_value(value, key)
                    try:
                        setattr(self.settings, key, coerced)
                        # Ensure __dict__ contains coerced values for downstream consumers
                        coerced_updates[key] = coerced
                    except Exception as e:
                        import logging

                        logging.warning(
                            f"Failed to set attribute '{key}' on settings: {e}"
                        )

            # In pydantic v2, extras may live outside __dict__. Update __dict__ for consumers
            # that expect direct dict access (e.g., tests using model.settings.__dict__).
            if coerced_updates:
                try:
                    self.settings.__dict__.update(coerced_updates)
                except Exception:
                    # Best-effort: if __dict__ is not writable, ignore silently
                    # (attributes have already been set above).
                    pass


def validate_normalized_config(config: Dict[str, Any]) -> NormalizedConfigModel:
    """Validate a normalized config dict using Pydantic models.

    Parameters
    ----------
    config
        Configuration in the internal normalized format returned by `normalize_config`.

    Returns
    -------
    NormalizedConfigModel
        The validated, typed model. Use `.model_dump()` to get a plain dict back.

    Raises
    ------
    pydantic.ValidationError
        If the configuration does not match the schema or invariants.
    ValueError
        If cross-reference checks fail (e.g., unknown node references).
    """
    # Accept only dict-like input here; normalization should already have ensured structure.
    if not isinstance(config, dict):
        raise TypeError("validate_normalized_config expects a mapping/dict")

    return NormalizedConfigModel(**config)
