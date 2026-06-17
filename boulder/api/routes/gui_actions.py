"""GUI action plugin API routes."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()


class GuiActionRunRequest(BaseModel):
    """Payload sent when the user clicks a toolbar action button."""

    config: Optional[Dict[str, Any]] = None
    config_yaml: Optional[str] = None
    filename: Optional[str] = None
    simulation_id: Optional[str] = None


def _build_context(request: Request, body: Optional[GuiActionRunRequest] = None) -> Any:
    from ...gui_actions import GuiActionContext
    from ...result_cache import (
        cache_dir_for,
        lookup_cached_result,
        resolve_mechanism_for_fingerprint,
    )

    preloaded_config = getattr(request.app.state, "preloaded_config", None)
    preloaded_yaml = getattr(request.app.state, "preloaded_yaml", None)
    preloaded_filename = getattr(request.app.state, "preloaded_filename", None)
    preloaded_config_path = getattr(request.app.state, "preloaded_config_path", None)

    config = preloaded_config
    config_yaml = preloaded_yaml
    filename = preloaded_filename
    simulation_id: Optional[str] = None

    if body is not None:
        if body.config is not None:
            config = body.config
        if body.config_yaml is not None:
            config_yaml = body.config_yaml
        if body.filename is not None:
            filename = body.filename
        simulation_id = body.simulation_id

    simulation_data = None
    if simulation_id:
        from .simulations import get_completed_simulation_data

        simulation_data = get_completed_simulation_data(simulation_id)

    preloaded_result = getattr(request.app.state, "preloaded_result", None)
    preloaded_fingerprint = getattr(request.app.state, "preloaded_fingerprint", None)
    has_cached_result = preloaded_result is not None
    cache_fingerprint = preloaded_fingerprint

    if body is not None and body.config is not None and isinstance(config, dict):
        converter_cls = getattr(request.app.state, "converter_class", None)
        mechanism = resolve_mechanism_for_fingerprint(
            config, converter_class=converter_cls
        )
        cache_root = cache_dir_for(preloaded_config_path)
        fingerprint, cached = lookup_cached_result(
            cache_root,
            dict(config),
            mechanism=mechanism,
            preloaded_result=preloaded_result,
        )
        cache_fingerprint = fingerprint
        has_cached_result = cached is not None

    return GuiActionContext(
        config=config,
        config_yaml=config_yaml,
        filename=filename,
        simulation_id=simulation_id,
        config_path=preloaded_config_path,
        simulation_data=simulation_data,
        has_cached_result=has_cached_result,
        cache_fingerprint=cache_fingerprint,
    )


@router.get("")
async def list_actions(request: Request) -> list[Dict[str, Any]]:
    """Return metadata for GUI actions available in the current context.

    Each entry includes ``is_available`` so the frontend can disable the
    button when the server knows the action cannot run yet (e.g. no cache
    and no completed simulation).
    """
    from ...gui_actions import get_gui_action_registry

    registry = get_gui_action_registry()
    context = _build_context(request)
    return [
        {
            "id": action.action_id,
            "label": action.label,
            "requires_simulation": action.requires_simulation,
            "is_available": action.is_available(context),
        }
        for action in registry.get_listed_actions(context)
    ]


@router.post("/{action_id}/run")
async def run_action(
    action_id: str,
    body: GuiActionRunRequest,
    request: Request,
) -> Response:
    """Execute a GUI action and return its output as a file download."""
    from ...gui_actions import get_gui_action_registry

    registry = get_gui_action_registry()
    action = registry.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")

    context = _build_context(request, body)
    if not action.is_available(context):
        raise HTTPException(
            status_code=400,
            detail="Action not available for current context",
        )

    try:
        result = action.run(context)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )
