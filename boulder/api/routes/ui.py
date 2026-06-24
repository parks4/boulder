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
