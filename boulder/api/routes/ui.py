"""Lightweight UI-preferences endpoints.

A place for the frontend to publish small bits of UI state that other local
tools (e.g. an external dashboard) may want to mirror — currently just the
light/dark theme. Stored in-memory on ``app.state``; not persisted.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class ThemeBody(BaseModel):
    theme: str


@router.get("/theme")
async def get_theme(request: Request) -> Dict[str, Any]:
    """Return the theme the GUI last published (``light``/``dark``/``None``)."""
    return {"theme": getattr(request.app.state, "ui_theme", None)}


@router.post("/theme")
async def set_theme(body: ThemeBody, request: Request) -> Dict[str, Any]:
    """Publish the GUI's current theme so external tools can mirror it."""
    theme = body.theme if body.theme in ("light", "dark") else None
    request.app.state.ui_theme = theme
    return {"theme": theme}


@router.get("/kind-schema/{kind}")
async def get_kind_schema(kind: str) -> Dict[str, Any]:
    """JSON schema for a node or connection kind (``schema: null`` if none).

    Serves the declarative Pydantic schemas plugins register for their
    kinds; the property panel uses it for field descriptions (tooltips),
    enum options (dropdowns) and conditional visibility.
    """
    from ...schema_registry import get_kind_schema_json

    try:
        schema = get_kind_schema_json(kind)
    except Exception:  # noqa: BLE001 - introspection must never break the UI
        schema = None
    return {"kind": kind, "schema": schema}


@router.get("/kinds")
async def get_kinds() -> Dict[str, Any]:
    """List every reactor and connection kind the running Boulder can build.

    Combines Boulder's built-in kinds (with a Cantera doc link/description
    from :mod:`boulder.cantera_docs`) with any kind a loaded plugin has
    registered via ``schema_registry.register_reactor_builder`` (doc link
    only if the plugin passed ``doc_url``/``doc_description``) or
    ``register_connection_schema`` (no doc link — plugins document their own
    connection kinds). Powers the Add Reactor/Add Connection modals so the
    type dropdown always reflects what this build can actually construct.
    """
    from ...cantera_docs import CONNECTION_DOCS, REACTOR_DOCS
    from ...schema_registry import (
        get_schema_entry,
        registered_connection_kinds,
        registered_kinds,
    )

    reactors = [
        {"kind": kind, "doc_url": doc["doc_url"], "description": doc["description"]}
        for kind, doc in REACTOR_DOCS.items()
    ] + [
        {
            "kind": kind,
            "doc_url": (entry := get_schema_entry(kind)) and entry.doc_url,
            "description": entry and entry.doc_description,
        }
        for kind in registered_kinds()
        if kind not in REACTOR_DOCS
    ]
    connections = [
        {"kind": kind, "doc_url": doc["doc_url"], "description": doc["description"]}
        for kind, doc in CONNECTION_DOCS.items()
    ] + [
        {"kind": kind, "doc_url": None, "description": None}
        for kind in registered_connection_kinds()
        if kind not in CONNECTION_DOCS
    ]
    return {"reactors": reactors, "connections": connections}


@router.get("/branding")
async def get_branding() -> Dict[str, Any]:
    """Return the host branding set by a plugin (name/version), if any.

    The header shows ``Boulder`` alone when no plugin declares branding, and
    the host name and version when a host package does.
    """
    from ...cantera_converter import get_plugins

    try:
        branding = get_plugins().branding
    except Exception:  # noqa: BLE001 - branding must never break the UI
        branding = None
    return {"branding": branding}


@router.get("/header-links")
async def get_header_links() -> Dict[str, Any]:
    """Return the top-bar links host plugins registered (``[]`` when none)."""
    from ...cantera_converter import get_plugins

    return {"links": get_plugins().header_links}


_STATUS_TONES = ("ok", "warn", "error", "neutral")


def _recorded_config(store_dir: Any, sid: str) -> Optional[Dict[str, Any]]:
    """Return the definition a stored entry was solved from, expanded to *sid*."""
    from ruamel.yaml import YAML

    from ... import scenario_store
    from ...runset import expand_scenarios

    source = scenario_store.read_source(store_dir, sid)
    if source is None:
        return None
    definition = YAML(typ="safe").load(source.definition)
    return dict(expand_scenarios(definition)).get(sid)


@router.get("/header-status")
def get_header_status(
    request: Request, scenario_id: Optional[str] = None
) -> Dict[str, Any]:
    """Resolve the host's status chip for one scenario (the base run when omitted).

    The host's ``plugins.header_status`` provider gets the raw store id, the stored
    entry's fingerprints (``()`` when nothing is stored; exact) and a config: the
    stored entry's recorded definition for a stored id (``None`` when none was
    recorded), else the last parsed or uploaded YAML expanded with its saved
    scenarios. Unsaved GUI edits and in-memory overlays are not included.
    Answers ``{"status": null}`` when there is no provider or it returns
    ``None``, 404 for an id that is neither stored nor authored, and 500 (with the
    detail) when the provider raises or returns a bad text, tone, tooltip or href.

    A plain ``def`` so FastAPI runs it in its threadpool: the provider and the
    store reads may be slow.
    """
    from ... import scenario_store
    from ...cantera_converter import (
        HeaderStatusContext,
        get_plugins,
        validate_header_href,
    )
    from ...runset import base_entry_id, expand_scenarios
    from .scenarios import _identity, _require_base_raw, _store_dir

    provider = get_plugins().header_status
    if provider is None:
        return {"status": None}

    raw = _require_base_raw(request)
    sid = scenario_id or base_entry_id(raw)
    stored = {
        str(e["id"]): e
        for e in scenario_store.list_entries(_store_dir(request), _identity(request))
    }
    expanded = dict(expand_scenarios(raw))
    if sid not in stored and sid not in expanded and sid != base_entry_id(raw):
        raise HTTPException(status_code=404, detail=f"Unknown scenario {sid!r}")
    entry = stored.get(sid)
    if entry is not None:
        config = _recorded_config(_store_dir(request), sid)
        if config is None and sid == base_entry_id(raw):
            config = raw
    else:
        config = expanded.get(sid, raw)
    ctx = HeaderStatusContext(
        config=config,
        scenario_id=sid,
        fingerprints=scenario_store.entry_fingerprints(entry) if entry else (),
    )
    try:
        status = provider(ctx)
        if status is None:
            return {"status": None}
        tone = status["tone"]
        if tone not in _STATUS_TONES:
            raise ValueError(f"tone must be one of {_STATUS_TONES}, got {tone!r}")
        text, tooltip = status["text"], status.get("tooltip")
        if not isinstance(text, str) or not text:
            raise ValueError(f"text must be a non-empty string, got {text!r}")
        if tooltip is not None and not isinstance(tooltip, str):
            raise ValueError(f"tooltip must be a string or None, got {tooltip!r}")
        href = status.get("href")
        if href is not None:
            validate_header_href(href)
        return {
            "status": {
                "text": text,
                "tone": tone,
                "href": href,
                "tooltip": tooltip,
                "new_tab": bool(status.get("new_tab", False)),
            }
        }
    except Exception as exc:  # noqa: BLE001 - a host provider's failure is reported, not hidden
        raise HTTPException(
            status_code=500, detail=f"header_status provider failed: {exc}"
        ) from exc


@router.get("/species-colors")
async def get_species_colors() -> Dict[str, Any]:
    """Return the species -> hex color palette set by a plugin, if any.

    Boulder has no built-in notion of which color belongs to which species;
    a host plugin may register one (the same palette already used to color
    the Sankey diagram's species bands, via ``plugins.sankey_link_colors``)
    so other charts can render a given species consistently.
    """
    from ...cantera_converter import get_plugins

    try:
        species_colors = get_plugins().sankey_link_colors
    except Exception:  # noqa: BLE001 - this must never break the UI
        species_colors = None
    return {"species_colors": species_colors or {}}
