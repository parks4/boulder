"""Graph element and stylesheet API routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...styles import get_cytoscape_stylesheet
from ...utils import config_to_cyto_elements

router = APIRouter()


class GraphElementsRequest(BaseModel):
    config: Dict[str, Any]


@router.post("/elements")
async def get_graph_elements(body: GraphElementsRequest) -> List[Dict[str, Any]]:
    """Convert a config dict to Cytoscape-compatible elements (nodes + edges)."""
    try:
        return config_to_cyto_elements(body.config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stylesheet")
async def get_stylesheet(theme: str = "light") -> List[Dict[str, Any]]:
    """Return the Cytoscape stylesheet for the given theme.

    Query parameter ``theme`` can be ``light`` or ``dark``.
    """
    try:
        return get_cytoscape_stylesheet(theme)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
