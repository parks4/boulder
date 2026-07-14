"""Lightweight UI-preferences endpoints.

A place for the frontend to publish small bits of UI state that other local
tools (e.g. an external dashboard) may want to mirror — currently just the
light/dark theme. Stored in-memory on ``app.state``; not persisted.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
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
    registered via ``schema_registry.register_reactor_builder``/
    ``register_connection_schema`` (no doc link — plugins document their own
    kinds). Powers the Add Reactor/Add Connection modals so the type
    dropdown always reflects what this build can actually construct.
    """
    from ...cantera_docs import CONNECTION_DOCS, REACTOR_DOCS
    from ...schema_registry import registered_connection_kinds, registered_kinds

    reactors = [
        {"kind": kind, "doc_url": doc["doc_url"], "description": doc["description"]}
        for kind, doc in REACTOR_DOCS.items()
    ] + [
        {"kind": kind, "doc_url": None, "description": None}
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
