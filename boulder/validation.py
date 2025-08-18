"""Schema and validation utilities for normalized configuration.

This module defines Pydantic models for Boulder internal (normalized) config and exposes a
`validate_normalized_config` function that validates dictionaries after `normalize_config`.

Validation is schema-only and does not build or inspect any simulation network.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from pint import UnitRegistry
from pydantic import BaseModel, Field, field_validator, model_validator


class SimulationModel(BaseModel):
    """Simulation section of the normalized config.

    Open schema by design: accept arbitrary keys (e.g., mechanisms, time settings).
    """

    class Config:
        extra = "allow"


class NodeModel(BaseModel):
    """Node entry in `nodes` list of normalized config."""

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    properties: Dict[str, Any] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("properties")
    @classmethod
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

    @field_validator("properties")
    @classmethod
    def ensure_properties_is_object(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("connection.properties must be a mapping/dict")
        return value


class NormalizedConfigModel(BaseModel):
    """Top-level normalized configuration model."""

    metadata: Optional[Dict[str, Any]] = None
    simulation: Optional[SimulationModel] = None
    nodes: List[NodeModel]
    connections: List[ConnectionModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references_and_uniqueness(self) -> "NormalizedConfigModel":
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

        return self

    @model_validator(mode="after")
    def coerce_units(self) -> "NormalizedConfigModel":
        """Coerce unit-bearing strings to canonical units using pint.

        Mirrors ctwrap behavior: values defined as strings with units are converted
        to base magnitudes in consistent units. Unknown keys remain unchanged.
        """
        unit_registry = UnitRegistry()

        node_units: Dict[str, str] = {
            "temperature": "kelvin",
            "pressure": "pascal",
            "mass": "kilogram",
            "volume": "meter**3",
            "flow_rate": "kg/second",
            "mass_flow_rate": "kg/second",
            "time_constant": "second",
        }

        sim_units: Dict[str, str] = {
            "dt": "second",
            "end_time": "second",
            "max_time": "second",
        }

        def _coerce_value(val: Any, unit: str) -> Any:
            if isinstance(val, str):
                try:
                    qty = unit_registry.Quantity(val)
                    return qty.to(unit).magnitude
                except Exception:
                    return val
            return val

        for node in self.nodes:
            for key, unit in node_units.items():
                if key in node.properties:
                    node.properties[key] = _coerce_value(node.properties[key], unit)

        for conn in self.connections:
            for key, unit in node_units.items():
                if key in conn.properties:
                    conn.properties[key] = _coerce_value(conn.properties[key], unit)

        if isinstance(self.simulation, SimulationModel):
            for key, unit in sim_units.items():
                if hasattr(self.simulation, key):
                    current = getattr(self.simulation, key)
                    coerced = _coerce_value(current, unit)
                    try:
                        setattr(self.simulation, key, coerced)
                    except Exception:
                        pass

        return self


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

    return NormalizedConfigModel.model_validate(config)
