"""Schema and validation utilities for normalized configuration.

This module defines Pydantic models for Boulder internal (normalized) config and exposes a
`validate_normalized_config` function that validates dictionaries after `normalize_config`.

Validation is schema-only and does not build or inspect any simulation network.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, validator

#: Detect strings that look like "number unit" — mirrors the regex in utils.py
#: and is used only to decide whether to surface a helpful error message.
_LOOKS_LIKE_UNIT_RE = re.compile(
    r"^\s*[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\s+\S", re.ASCII
)


def _looks_like_unit_string(val: str) -> bool:
    return bool(_LOOKS_LIKE_UNIT_RE.match(val))


try:
    from typing import Literal  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - py<3.8
    from typing_extensions import Literal  # type: ignore[assignment]


class InletPort(BaseModel):
    """Reactor-node inlet port shortcut.

    Synthesised by :func:`boulder.config.expand_port_shortcuts` into a regular
    ``MassFlowController`` entry in ``connections:``.  Omitting
    ``mass_flow_rate`` asks the conservation resolver
    (:func:`boulder.cantera_converter.resolve_unset_flow_rates`) to fill it.
    """

    source: str = Field(
        ...,
        alias="from",
        description="Id of the upstream node feeding this reactor.",
    )
    mass_flow_rate: Optional[float] = Field(
        default=None,
        description=(
            "[kg/s] Optional explicit flow rate; omit to let global mass "
            "conservation determine it from the rest of the topology."
        ),
    )

    class Config:
        populate_by_name = True
        extra = "forbid"


class OutletPort(BaseModel):
    """Reactor-node outlet port shortcut.

    By default expands to a ``PressureController`` with ``pressure_coeff=0``
    so ``m_out = m_in`` at every timestep without a placeholder mass flow
    rate.  Set ``device='MassFlowController'`` to get an MFC instead (useful
    when the reactor has several inlets and the PressureController master is
    ambiguous).
    """

    to: str = Field(
        ...,
        description="Id of the downstream node receiving this reactor's flow.",
    )
    device: Literal["PressureController", "MassFlowController"] = Field(
        default="PressureController",
        description="Cantera flow device kind to synthesise.",
    )
    pressure_coeff: float = Field(
        default=0.0,
        description=(
            "[kg/s/Pa] PressureController pressure coefficient; 0 locks "
            "m_out = m_primary at every step."
        ),
    )
    master: Optional[str] = Field(
        default=None,
        description=(
            "Id of the inlet MassFlowController that drives this "
            "PressureController.  When omitted, the expander auto-picks "
            "the unique inlet MFC; a multi-inlet reactor must set this "
            "explicitly or switch to device='MassFlowController'."
        ),
    )
    mass_flow_rate: Optional[float] = Field(
        default=None,
        description=(
            "[kg/s] Only used when device='MassFlowController'; omit to let "
            "global mass conservation resolve it."
        ),
    )

    class Config:
        extra = "forbid"


#: Locked STONE ``metadata:`` vocabulary.  Mandatory keys identify the
#: scenario and are consumed by reporting code (calc_note, report, ...).
#: Optional keys cover documentation/provenance fields we standardise so
#: report generators can rely on them.  Anything outside this vocabulary
#: must live under ``metadata.extra:`` — this keeps the '# [unit] desc |
#: remark' YAML comment convention intact at the value level.
METADATA_MANDATORY_KEYS: frozenset = frozenset({"description"})

METADATA_OPTIONAL_KEYS: frozenset = frozenset(
    {
        "scenario_id",
        "title",
        "name",
        "scenario_name",
        "architecture",
        "author",
        "date",
        "project",
        "version",
        "assumptions",
        "remarks",
        # Documentation / control metadata commonly used in engineering notes
        "pid_no",
        "tag_name",
        "doc_no",
        "rev",
        "checked_by",
        "approved_by",
        "client",
        # Provenance
        "original_yaml",
        "part1_stone_yaml",
        "source_file",
        # Escape hatch for truly freeform user metadata
        "extra",
    }
)

METADATA_ALLOWED_KEYS: frozenset = METADATA_MANDATORY_KEYS | METADATA_OPTIONAL_KEYS

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


class MetadataModel(BaseModel):
    """STONE ``metadata:`` block with a locked vocabulary.

    Mandatory keys (:data:`METADATA_MANDATORY_KEYS`) identify the scenario
    and feed the report headers.  A set of well-known optional keys covers
    authoring, provenance, and document-control fields.  Anything
    user-specific must live under ``metadata.extra:`` so report generators
    do not need to branch on ad-hoc top-level fields.

    The ``# [unit] desc | remark`` YAML comment convention applies to
    individual values and is preserved by ``ruamel.yaml``; this schema
    only governs *which* keys are accepted.
    """

    description: Optional[str] = None

    scenario_id: Optional[str] = None
    title: Optional[str] = None
    name: Optional[str] = None
    scenario_name: Optional[str] = None
    architecture: Optional[str] = None
    author: Optional[str] = None
    # Date is kept untyped so YAML can emit either strings or date objects
    date: Optional[Any] = None
    project: Optional[str] = None
    version: Optional[str] = None
    assumptions: Optional[List[Any]] = None
    remarks: Optional[Dict[str, Any]] = None

    pid_no: Optional[str] = None
    tag_name: Optional[str] = None
    doc_no: Optional[str] = None
    rev: Optional[str] = None
    checked_by: Optional[str] = None
    approved_by: Optional[str] = None
    client: Optional[str] = None

    original_yaml: Optional[str] = None
    part1_stone_yaml: Optional[str] = None
    source_file: Optional[str] = None

    extra: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "forbid"


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
    #: Staged-solving group tag (set automatically by normalize_config's
    #: default-group synthesis when the YAML has no ``groups:`` section).
    group: Optional[str] = None
    #: Optional dotted path or import ref pointing to a custom
    #: ``ct.ReactorNet`` subclass; takes precedence over ``NETWORK_CLASS``
    #: class attributes during staged solving.
    network_class: Optional[str] = None

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
    #: Optional mechanism-switch annotation for inter-stage connections.
    #: ``{"htol": float, "Xtol": float}``
    mechanism_switch: Optional[Dict[str, Any]] = None
    #: Staged-solving group tag (same semantics as NodeModel.group).
    group: Optional[str] = None
    #: True when this connection was synthesized from a STONE v2 logical
    #: (kind-less) inter-stage edge.  The downstream staged solver uses this
    #: flag to skip Cantera device instantiation and instead copy state.
    logical: Optional[bool] = None

    @validator("properties")
    def ensure_properties_is_object(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("connection.properties must be a mapping/dict")
        return value


class NormalizedConfigModel(BaseModel):
    """Top-level normalized configuration model."""

    metadata: Optional[MetadataModel] = None
    phases: Optional[PhasesModel] = None
    settings: Optional[SettingsModel] = None
    nodes: List[NodeModel]
    connections: List[ConnectionModel] = Field(default_factory=list)
    # Preserve top-level `output` block (flexible shape). Validation of its content
    # is handled by feature-specific parsers; we just carry it through here.
    output: Optional[Any] = None
    #: Staged-solving group definitions.
    #: ``{group_id: {stage_order, mechanism, solve, advance_time}}``
    groups: Optional[Dict[str, Any]] = None

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

        # Build a set of OutletSink node ids for source validation.
        outlet_sink_ids: Set[str] = {n.id for n in self.nodes if n.type == "OutletSink"}

        # Source/target references must exist (node id or node_id_outlet alias)
        valid_nodes: Set[str] = set(node_ids)

        def _valid_ref(ref: str) -> bool:
            if ref in valid_nodes:
                return True
            if ref.endswith("_outlet") and ref[:-7] in valid_nodes:
                return True
            return False

        for conn in self.connections:
            if not _valid_ref(conn.source):
                raise ValueError(
                    f"Connection '{conn.id}' source '{conn.source}' does not reference an existing node"
                )
            if not _valid_ref(conn.target):
                raise ValueError(
                    f"Connection '{conn.id}' target '{conn.target}' does not reference an existing node"
                )
            # OutletSink nodes cannot be connection sources.
            if conn.source in outlet_sink_ids:
                raise ValueError(
                    f"Connection '{conn.id}' uses 'OutletSink' node '{conn.source}' as source. "
                    "OutletSink is a visualization-only terminal node and cannot be a source. "
                    "See STONE_SPECIFICATIONS.md."
                )

        by_conn_id = {c.id: c for c in self.connections}
        for conn in self.connections:
            if conn.type == "PressureController":
                master = (conn.properties or {}).get("master")
                if not master or not str(master).strip():
                    raise ValueError(
                        f"Connection '{conn.id}' (PressureController) must set "
                        f"properties.master to the id of a MassFlowController connection."
                    )
                if master not in seen_conns:
                    raise ValueError(
                        f"Connection '{conn.id}': PressureController master "
                        f"'{master}' is not a connection id. Declare the master "
                        f"MassFlowController first (or use an `inlet:` port)."
                    )
                if master == conn.id:
                    raise ValueError(
                        f"Connection '{conn.id}': PressureController cannot be its own master."
                    )
                mconn = by_conn_id.get(master)
                if mconn is not None and mconn.type != "MassFlowController":
                    raise ValueError(
                        f"Connection '{conn.id}': PressureController master "
                        f"'{master}' must reference a MassFlowController, not "
                        f"'{mconn.type}'."
                    )

        # Ambiguous conservation: multiple empty MFCs outgoing from the same source node.
        # An "empty" MFC has no explicit mass_flow_rate (or mass_flow_rate is None).
        empty_mfc_sources: Dict[str, List[str]] = {}
        for conn in self.connections:
            if conn.type == "MassFlowController" and not conn.logical:
                mfr = (conn.properties or {}).get("mass_flow_rate")
                if mfr is None:
                    empty_mfc_sources.setdefault(conn.source, []).append(conn.id)
        for src, mfc_ids in empty_mfc_sources.items():
            if len(mfc_ids) > 1:
                raise ValueError(
                    f"Ambiguous conservation: node '{src}' has {len(mfc_ids)} outgoing "
                    f"MassFlowController connections with no explicit mass_flow_rate "
                    f"({mfc_ids}). Conservation cannot uniquely determine the split. "
                    "Set 'mass_flow_rate:' on all but one, or on all. "
                    "See STONE_SPECIFICATIONS.md."
                )

    def _coerce_units(self) -> None:
        """Coerce unit-bearing strings in node/connection/settings properties.

        Delegates to :func:`boulder.utils.coerce_unit_string` so the
        conversion rules (Pint-based, temperature → Kelvin, pressure → Pa,
        …) are defined in one place and reused by both :func:`normalize_config`
        and the Pydantic validation layer.

        When the config passes through :func:`normalize_config` first (the
        normal simulation path), values are already floats and this method
        is a no-op.  When callers construct a :class:`NormalizedConfigModel`
        directly from a dict (unit tests, CLI ``validate``), the coercion
        fires here instead.
        """
        from .utils import _PROPERTY_UNIT_HINTS, coerce_unit_string  # noqa: PLC0415

        # Provide a helpful error on unknown/invalid unit strings by wrapping
        # coerce_unit_string and re-raising with context.
        def _coerce(val: Any, prop: str) -> Any:
            result = coerce_unit_string(val, property_name=prop)
            if result is val and isinstance(val, str) and _looks_like_unit_string(val):
                # coerce_unit_string returned the original string unchanged —
                # likely an invalid unit.  Surface an actionable error.
                # Look up suggestion first by property name, then by its
                # canonical target-unit name (e.g. "temperature" → "kelvin").
                canonical = _PROPERTY_UNIT_HINTS.get(prop, prop)
                unit_hint = UNIT_SUGGESTIONS.get(prop) or UNIT_SUGGESTIONS.get(
                    canonical,
                    "valid units (e.g. 'degC', 'bar', 'kg/s', 'ms')",
                )
                raise ValueError(
                    f"Could not convert '{val}' for property '{prop}'. "
                    f"Please use {unit_hint}."
                )
            return result

        for node in self.nodes:
            for key, value in list(node.properties.items()):
                node.properties[key] = _coerce(value, key)

        for conn in self.connections:
            for key, value in list(conn.properties.items()):
                conn.properties[key] = _coerce(value, key)

        if isinstance(self.settings, SettingsModel):
            settings_data = (
                self.settings.dict()
                if hasattr(self.settings, "dict")
                else self.settings.__dict__
            )
            for key, value in settings_data.items():
                coerced = _coerce(value, key) if isinstance(value, str) else value
                try:
                    setattr(self.settings, key, coerced)
                    # Pydantic v2 stores extra fields in model_extra, not __dict__.
                    # Mirror coerced values into __dict__ so that downstream code
                    # using model.settings.__dict__["dt"] keeps working.
                    self.settings.__dict__[key] = coerced
                except Exception:
                    pass


def warn_flow_device_conventions(config: Dict[str, Any]) -> List[str]:
    """Return non-fatal notes about ``MassFlowController`` values that are often legacies.

    A declared ``mass_flow_rate: 0.0`` is valid for a intentionally closed
    side feed (e.g. ``feed_secondary`` in SPRING) but is also the obsolete
    placeholder for a tube-furnace outlet; :func:`warn_flow_device_conventions`
    nudges authors toward :func:`boulder.config.expand_port_shortcuts` or
    omitting the rate.  Call from ``boulder validate`` only — not from every
    :func:`boulder.config.validate_config` invocation, to keep library calls quiet.
    """
    messages: List[str] = []
    for raw in config.get("connections") or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") != "MassFlowController":
            continue
        props = raw.get("properties") or {}
        mfr = props.get("mass_flow_rate")
        if mfr is None:
            continue
        try:
            if float(mfr) != 0.0:
                continue
        except (TypeError, ValueError):
            continue
        cid = raw.get("id", "?")
        messages.append(
            f"Connection '{cid}' has mass_flow_rate: 0.0. If this is a main "
            f"outlet, use a reactor `outlet:` port (PressureController) or omit "
            f"mass_flow_rate; 0.0 is OK for a deliberately closed side feed."
        )
    return messages


def warn_simulation_quality(config: Dict[str, Any]) -> List[str]:
    """Return non-fatal notes for configurations that are valid but uninformative.

    These checks intentionally do not fail validation: they guide authors toward
    practical defaults without blocking intentionally minimal/diagnostic cases.
    """
    messages: List[str] = []
    output_block = config.get("output")

    if output_block is None:
        messages.append(
            "No top-level 'output:' block configured. The simulation can run, but there may be "
            "no structured results selected for reporting/export."
        )
        return messages

    if output_block == {} or output_block == []:
        messages.append(
            "Top-level 'output:' block is empty. Configure at least one output target "
            "(temperature, pressure, composition, custom summary, etc.)."
        )

    return messages


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
