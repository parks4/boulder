"""Plugin registry and rendering API routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class PluginRenderRequest(BaseModel):
    """Context sent to a plugin for rendering."""
    simulation_data: Optional[Dict[str, Any]] = None
    selected_element: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    theme: str = "light"


@router.get("")
async def list_plugins() -> List[Dict[str, Any]]:
    """Return metadata for all registered output-pane plugins."""
    try:
        from ...output_pane_plugins import get_output_pane_registry

        registry = get_output_pane_registry()
        result = []
        for plugin in registry.plugins:
            result.append({
                "id": plugin.plugin_id,
                "label": plugin.tab_label,
                "icon": getattr(plugin, "tab_icon", None),
                "requires_selection": getattr(plugin, "requires_selection", False),
                "supported_element_types": getattr(
                    plugin, "supported_element_types", ["reactor"]
                ),
            })
        return result
    except ImportError:
        return []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{plugin_id}/render")
async def render_plugin(
    plugin_id: str,
    body: PluginRenderRequest,
) -> Dict[str, Any]:
    """Render a plugin and return JSON-serialisable data.

    The frontend receives structured data (images, tables, HTML snippets)
    and renders it in a generic ``PluginTab`` component.
    """
    try:
        from ...output_pane_plugins import (
            OutputPaneContext,
            get_output_pane_registry,
        )

        registry = get_output_pane_registry()
        plugin = registry.get_plugin(plugin_id)
        if plugin is None:
            raise HTTPException(
                status_code=404, detail=f"Plugin '{plugin_id}' not found"
            )

        context = OutputPaneContext(
            simulation_data=body.simulation_data,
            selected_element=body.selected_element,
            config=body.config,
            theme=body.theme,
        )

        if not plugin.is_available(context):
            return {"available": False, "message": "Plugin not available for current context"}

        data = plugin.create_content_data(context)
        return {"available": True, "data": data}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
