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

    return GuiActionContext(
        config=config,
        config_yaml=config_yaml,
        filename=filename,
        simulation_id=simulation_id,
        config_path=preloaded_config_path,
        simulation_data=simulation_data,
    )


@router.get("")
async def list_actions(request: Request) -> list[Dict[str, Any]]:
    """Return metadata for GUI actions available in the current context."""
    from ...gui_actions import get_gui_action_registry

    registry = get_gui_action_registry()
    context = _build_context(request)
    return [
        {
            "id": action.action_id,
            "label": action.label,
            "requires_simulation": action.requires_simulation,
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

    result = action.run(context)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )
