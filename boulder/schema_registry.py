"""Schema registry for pluggable reactor kinds.

Plugin packages registering new reactor kinds with Boulder can opt into
a declarative schema (Pydantic ``BaseModel``) plus reporting metadata
(categories, default constraints).  This turns the YAML into the single
source of truth for a simulation: ``boulder validate`` and
``boulder describe`` use these entries to check YAML files and auto-render
property panes without running Cantera.

Backward compatibility
----------------------
Plugins that still write directly to ``plugins.reactor_builders[kind]``
without using :func:`register_reactor_builder` keep working exactly as
before; they simply do not benefit from schema validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

_PydBaseModel: Optional[Type[Any]]
_PydValidationError: type[BaseException]
try:  # pydantic is an existing boulder dependency (>=2.0)
    from pydantic import BaseModel as _ImportedBaseModel
    from pydantic import ValidationError as _ImportedValidationError

    _PydBaseModel = _ImportedBaseModel
    _PydValidationError = _ImportedValidationError
except ImportError:  # pragma: no cover - pydantic is required
    _PydBaseModel = None
    _PydValidationError = Exception

BaseModel: Optional[Type[Any]] = _PydBaseModel
ValidationError: type[BaseException] = _PydValidationError


@dataclass
class ReactorSchemaEntry:
    """Registration metadata attached to a reactor builder.

    Parameters
    ----------
    kind:
        YAML reactor key (e.g. ``"DesignTubeFurnace"``).
    builder:
        Callable ``(converter, node_dict) -> ct.Reactor``.
    network_class:
        Optional dotted-path string or class object pointing at a custom
        ``ReactorNet`` class.  Used by :class:`DualCanteraConverter` as
        ``NETWORK_CLASS`` override fallback.
    schema:
        Optional ``pydantic.BaseModel`` subclass describing the YAML
        properties accepted under the reactor kind.
    categories:
        ``{"inputs": {category: [keys]}, "outputs": {category: [keys]}}``
        — report-level grouping used by the Calculation Note.
    default_constraints:
        List of plain dicts ``{key, description, operator, threshold}``
        used as pass/fail criteria when the YAML does not declare any.
    variable_maps:
        ``{"inputs": {raw_key: (tag, unit, description)}, "outputs": {...}}``
        — human-readable mapping used when the Calculation Note renders
        variable columns.  Using tuples keeps this trivially JSON-serialisable
        and matches the legacy ``TF_*_VARIABLE_MAP`` shape one-for-one.
    """

    kind: str
    builder: Callable[..., Any]
    network_class: Optional[Any] = None
    schema: Optional[Type[Any]] = None
    categories: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    default_constraints: List[Dict[str, Any]] = field(default_factory=list)
    variable_maps: Dict[str, Dict[str, Any]] = field(default_factory=dict)


_SCHEMA_REGISTRY: Dict[str, ReactorSchemaEntry] = {}


def register_reactor_builder(
    plugins: Any,
    kind: str,
    builder: Callable[..., Any],
    *,
    network_class: Optional[Any] = None,
    schema: Optional[Type[Any]] = None,
    categories: Optional[Dict[str, Dict[str, List[str]]]] = None,
    default_constraints: Optional[List[Dict[str, Any]]] = None,
    variable_maps: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Register a reactor builder together with its declarative metadata.

    Mirrors the effect of ``plugins.reactor_builders[kind] = builder`` and
    additionally records a :class:`ReactorSchemaEntry` in the global
    registry so the CLI (``boulder validate`` / ``boulder describe``) and
    UI can introspect the plugin.
    """
    plugins.reactor_builders[kind] = builder
    entry = ReactorSchemaEntry(
        kind=kind,
        builder=builder,
        network_class=network_class,
        schema=schema,
        categories=dict(categories or {}),
        default_constraints=list(default_constraints or []),
        variable_maps=dict(variable_maps or {}),
    )
    _SCHEMA_REGISTRY[kind] = entry


def get_report_metadata_for_config(
    config: Dict[str, Any],
    *,
    explicit_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the Calculation-Note reporting metadata for a normalised config.

    Resolution order for the reactor kind:

    1. ``explicit_kind`` argument (comes from ``export.reactor_kind`` in the
       YAML or from a CLI override).
    2. The unique registered kind appearing in ``config['nodes']``.

    Raises
    ------
    ValueError
        When no registered kind is found or when the config contains several
        registered kinds and no ``explicit_kind`` was passed.
    """
    kind = explicit_kind
    if kind is None:
        present = []
        for node in config.get("nodes") or []:
            node_kind = node.get("type")
            if node_kind and node_kind in _SCHEMA_REGISTRY:
                present.append(node_kind)
        unique = sorted(set(present))
        if len(unique) == 1:
            kind = unique[0]
        elif len(unique) == 0:
            raise ValueError(
                "No registered reactor kind found in config.nodes; "
                "set export.reactor_kind explicitly."
            )
        else:
            raise ValueError(
                "Config contains several registered reactor kinds "
                f"({unique}); set export.reactor_kind explicitly."
            )

    entry = _SCHEMA_REGISTRY.get(kind)
    if entry is None:
        raise KeyError(
            f"Reactor kind {kind!r} has no registered schema entry. "
            f"Known: {registered_kinds()}"
        )
    return {
        "kind": entry.kind,
        "categories": entry.categories,
        "default_constraints": entry.default_constraints,
        "variable_maps": entry.variable_maps,
    }


def get_schema_entry(kind: str) -> Optional[ReactorSchemaEntry]:
    """Return the registered :class:`ReactorSchemaEntry` for *kind* or None."""
    return _SCHEMA_REGISTRY.get(kind)


def registered_kinds() -> List[str]:
    """Return the list of reactor kinds that have a registered schema entry."""
    return sorted(_SCHEMA_REGISTRY.keys())


def _iter_node_props(node: Dict[str, Any]) -> List[tuple]:
    """Yield ``(kind, prop_dict)`` tuples for a normalised node.

    Normalised nodes carry the kind both as ``type`` and as a nested block
    keyed by the kind name.  We accept either.
    """
    out: List[tuple] = []
    kind = node.get("type")
    props = node.get("properties") or {}
    if kind:
        out.append((kind, props))
    for key, val in node.items():
        if key in {"id", "type", "group", "description", "properties"}:
            continue
        if isinstance(val, dict) and key in _SCHEMA_REGISTRY:
            out.append((key, val))
    return out


def validate_against_plugin_schemas(config: Dict[str, Any]) -> List[str]:
    """Validate every node's properties against its registered schema.

    Returns a list of human-readable error strings (empty on success).
    """
    errors: List[str] = []
    if BaseModel is None:
        return errors
    for node in config.get("nodes") or []:
        nid = node.get("id", "<unknown>")
        for kind, props in _iter_node_props(node):
            entry = _SCHEMA_REGISTRY.get(kind)
            if entry is None or entry.schema is None:
                continue
            try:
                entry.schema(**(props or {}))
            except ValidationError as exc:
                # Pydantic's ValidationError exposes ``errors()``; the ImportError
                # fallback is plain ``Exception`` and we never call this when
                # ``BaseModel is None`` above.
                pexc: Any = exc
                for err in pexc.errors():
                    loc = ".".join(str(x) for x in err.get("loc", ()))
                    msg = err.get("msg", "invalid")
                    errors.append(f"node {nid!r} [{kind}].{loc}: {msg}")
            except TypeError as exc:
                errors.append(f"node {nid!r} [{kind}]: {exc}")
    return errors


def describe_kind(kind: str) -> Dict[str, Any]:
    """Return a plain-dict description of *kind* for introspection CLIs.

    Raises
    ------
    KeyError
        If *kind* is not registered.
    """
    entry = _SCHEMA_REGISTRY.get(kind)
    if entry is None:
        raise KeyError(
            f"Reactor kind {kind!r} has no registered schema entry. "
            f"Known: {registered_kinds()}"
        )
    schema_json: Optional[Dict[str, Any]] = None
    if entry.schema is not None and hasattr(entry.schema, "model_json_schema"):
        schema_json = entry.schema.model_json_schema()
    return {
        "kind": entry.kind,
        "builder": f"{entry.builder.__module__}.{entry.builder.__name__}",
        "network_class": _stringify(entry.network_class),
        "schema": _stringify(entry.schema),
        "schema_json": schema_json,
        "categories": entry.categories,
        "default_constraints": entry.default_constraints,
        "variable_maps": entry.variable_maps,
    }


def _stringify(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    module = getattr(obj, "__module__", "")
    name = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", str(obj))
    return f"{module}.{name}" if module else name
