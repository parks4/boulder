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


@router.get("/branding")
async def get_branding() -> Dict[str, Any]:
    """Return the host branding set by a plugin (name/version), if any.

    The header shows ``Boulder`` alone when no plugin declares branding, and
    ``Boulder · <name> <version>`` when a host package (e.g. rizer) does.
    """
    from ...cantera_converter import get_plugins

    try:
        branding = get_plugins().branding
    except Exception:  # noqa: BLE001 - branding must never break the UI
        branding = None
    return {"branding": branding}
