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

        # Try the new JSON-based API first, fall back to legacy
        if hasattr(plugin, "create_content_data"):
            data = plugin.create_content_data(context)
            return {"available": True, "data": data}

        # Fallback: render legacy Dash content and extract text/images
        try:
            content = plugin.create_content(context)
            # Best-effort extraction of useful data from Dash components
            return {
                "available": True,
                "data": _extract_data_from_dash_component(content),
            }
        except Exception:
            return {
                "available": True,
                "data": {"type": "text", "content": "Plugin rendered (legacy Dash content)"},
            }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _extract_data_from_dash_component(component: Any) -> Dict[str, Any]:
    """Best-effort extraction of data from a Dash component tree."""
    # Check for image components (e.g., NetworkPlugin returns an <img> with base64 src)
    if hasattr(component, "children"):
        children = component.children
        if isinstance(children, list):
            for child in children:
                result = _extract_data_from_dash_component(child)
                if result.get("type") != "text":
                    return result
        elif hasattr(children, "src"):
            return {"type": "image", "src": children.src, "alt": "Plugin output"}

    if hasattr(component, "src"):
        return {"type": "image", "src": component.src, "alt": "Plugin output"}

    if hasattr(component, "children") and isinstance(component.children, str):
        return {"type": "text", "content": component.children}

    return {"type": "text", "content": str(component)}
