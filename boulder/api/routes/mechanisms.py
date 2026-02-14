"""Mechanism listing API route."""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter

from ...utils import get_available_cantera_mechanisms

router = APIRouter()


@router.get("")
async def list_mechanisms() -> List[Dict[str, str]]:
    """Return the list of available Cantera mechanism files.

    Each entry has ``label`` and ``value`` keys suitable for
    populating a dropdown selector in the frontend.
    """
    return get_available_cantera_mechanisms()
