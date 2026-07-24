"""Cantera documentation links for built-in reactor and connection kinds.

Single source of truth for the doc-link tooltips the GUI shows next to a
reactor/connection's type (Properties panel, Add Reactor/Connection modals)
and for the network-gated CI check in ``tests/test_doc_links.py`` that these
anchors still resolve on cantera.org.

Only the STONE kinds Boulder builds natively in
:meth:`boulder.cantera_converter.DualCanteraConverter._build_reactor`/
``_build_connection`` are covered here. Plugin-registered kinds are
documented by the plugin itself (see ``boulder.schema_registry``) and are
not part of this map.
"""

from __future__ import annotations

from typing import Dict, TypedDict

#: Boulder supports a range of Cantera versions (pyproject.toml pins
#: ``cantera>=3.0.0``, no upper bound), so link to the version-agnostic
#: "stable" docs alias rather than a pinned version — the same convention
#: docs/cantera_examples/combustor.py already uses for its own citation.
_ZERODIM = "https://cantera.org/stable/python/zerodim.html"


class KindDoc(TypedDict):
    """Doc-link metadata for a single Cantera kind."""

    doc_url: str
    description: str


REACTOR_DOCS: Dict[str, KindDoc] = {
    "IdealGasReactor": {
        "doc_url": f"{_ZERODIM}#cantera.IdealGasReactor",
        "description": "Ideal-gas, constant-volume reactor.",
    },
    "ConstPressureReactor": {
        "doc_url": f"{_ZERODIM}#cantera.ConstPressureReactor",
        "description": "Constant-pressure reactor with variable volume.",
    },
    "IdealGasConstPressureReactor": {
        "doc_url": f"{_ZERODIM}#cantera.IdealGasConstPressureReactor",
        "description": "Ideal-gas, constant-pressure reactor with variable volume.",
    },
    "IdealGasConstPressureMoleReactor": {
        "doc_url": f"{_ZERODIM}#cantera.IdealGasConstPressureMoleReactor",
        "description": "Ideal-gas, constant-pressure reactor tracked in mole units.",
    },
    "IdealGasMoleReactor": {
        "doc_url": f"{_ZERODIM}#cantera.IdealGasMoleReactor",
        "description": "Ideal-gas, constant-volume reactor tracked in mole units.",
    },
    "Reservoir": {
        "doc_url": f"{_ZERODIM}#cantera.Reservoir",
        "description": "Infinite reservoir holding gas at a fixed state; used as a boundary.",
    },
}

CONNECTION_DOCS: Dict[str, KindDoc] = {
    "MassFlowController": {
        "doc_url": f"{_ZERODIM}#cantera.MassFlowController",
        "description": "Imposes a fixed or time-varying mass flow rate between two reactors.",
    },
    "Valve": {
        "doc_url": f"{_ZERODIM}#cantera.Valve",
        "description": "Flow device whose mass flow rate depends on the pressure difference.",
    },
    "PressureController": {
        "doc_url": f"{_ZERODIM}#cantera.PressureController",
        "description": "Mirrors a master MassFlowController while regulating downstream pressure.",
    },
    "Wall": {
        "doc_url": f"{_ZERODIM}#cantera.Wall",
        "description": "Wall between two reactors; can move and/or exchange heat.",
    },
}


def all_doc_urls() -> Dict[str, str]:
    """Flat ``kind -> doc_url`` map across reactors and connections.

    Used by the CI doc-link checker to enumerate every URL to probe.
    """
    return {
        kind: doc["doc_url"]
        for kind, doc in {**REACTOR_DOCS, **CONNECTION_DOCS}.items()
    }
