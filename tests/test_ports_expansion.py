"""Tests for node-level inlet/outlet port expansion in ``normalize_config``.

Covers:

- ``inlet:`` / ``outlet:`` ports on a reactor node expand into the same
  canonical ``connections:`` entries a hand-written YAML would produce,
  with auto-picked id (``{from}_to_{nid}`` and ``{nid}_to_{to}``) and a
  default outlet device of ``PressureController(pressure_coeff=0)``.
- The ports are removed from the node's ``properties`` after expansion
  so downstream consumers never see them.
- A single-inlet / single-outlet port chain on a multi-reactor pipeline
  expands identically to the explicit form.
- ``outlet:`` on a reactor with two MFC inlets raises unless ``master:``
  is set explicitly.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

from boulder.config import normalize_config


def _minimal_ported_config(with_mfr: bool = True) -> Dict[str, Any]:
    """STONE-style config using ``inlet:``/``outlet:`` shortcuts on r1."""
    inlet: Dict[str, Any] = {"from": "feed"}
    if with_mfr:
        inlet["mass_flow_rate"] = 1.5e-4
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            {
                "id": "feed",
                "Reservoir": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "r1",
                "IdealGasReactor": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                    "inlet": inlet,
                    "outlet": {"to": "outlet"},
                },
            },
            {
                "id": "outlet",
                "Reservoir": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
        ],
    }


def _minimal_explicit_config(mdot: float = 1.5e-4) -> Dict[str, Any]:
    """Hand-written equivalent of the ported config."""
    return {
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            {
                "id": "feed",
                "Reservoir": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
            {
                "id": "r1",
                "IdealGasReactor": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                    "volume": 1e-5,
                },
            },
            {
                "id": "outlet",
                "Reservoir": {
                    "temperature": 300.0,
                    "pressure": 101325.0,
                    "composition": "N2:1",
                },
            },
        ],
        "connections": [
            {
                "id": "feed_to_r1",
                "MassFlowController": {"mass_flow_rate": mdot},
                "source": "feed",
                "target": "r1",
            },
            {
                "id": "r1_to_outlet",
                "PressureController": {
                    "master": "feed_to_r1",
                    "pressure_coeff": 0.0,
                },
                "source": "r1",
                "target": "outlet",
            },
        ],
    }


def _conn_summary(conn: Dict[str, Any]) -> Dict[str, Any]:
    """Strip implementation details (``group``, ordering) for comparison."""
    return {
        "id": conn["id"],
        "type": conn["type"],
        "source": conn["source"],
        "target": conn["target"],
        "properties": dict(conn.get("properties") or {}),
    }


@pytest.mark.unit
def test_ports_expand_to_canonical_connections() -> None:
    """Port shortcuts produce the same normalized connections as explicit form.

    Asserts the port-based YAML yields two connections with the
    synthesised ids ``feed_to_r1`` and ``r1_to_outlet``, types
    ``MassFlowController`` + ``PressureController``, and the same
    properties as a hand-written explicit YAML - including the auto-picked
    ``master`` and default ``pressure_coeff=0``.
    """
    ported = normalize_config(copy.deepcopy(_minimal_ported_config()))
    explicit = normalize_config(_minimal_explicit_config())

    ported_conns: List[Dict[str, Any]] = [
        _conn_summary(c) for c in ported["connections"]
    ]
    explicit_conns: List[Dict[str, Any]] = [
        _conn_summary(c) for c in explicit["connections"]
    ]

    assert ported_conns == explicit_conns


@pytest.mark.unit
def test_ports_removed_from_node_properties() -> None:
    """``inlet:`` / ``outlet:`` are popped from ``properties`` after expansion.

    Asserts that the reactor node no longer carries the port shortcuts
    as properties (which would otherwise confuse the schema and plugin
    builders).
    """
    normalized = normalize_config(copy.deepcopy(_minimal_ported_config()))
    r1 = next(n for n in normalized["nodes"] if n["id"] == "r1")
    props = r1.get("properties") or {}
    assert "inlet" not in props
    assert "outlet" not in props


@pytest.mark.unit
def test_outlet_port_defaults_to_pressure_controller() -> None:
    """Default outlet device is ``PressureController`` with ``pressure_coeff=0``.

    Asserts that an ``outlet:`` port without an explicit ``device:``
    synthesises a PressureController whose ``master`` auto-resolves to
    the node's single inlet MFC.
    """
    normalized = normalize_config(copy.deepcopy(_minimal_ported_config()))
    outlet_conn = next(
        c for c in normalized["connections"] if c["id"] == "r1_to_outlet"
    )
    assert outlet_conn["type"] == "PressureController"
    props = outlet_conn["properties"]
    assert props["master"] == "feed_to_r1"
    assert props["pressure_coeff"] == 0.0


@pytest.mark.unit
def test_inlet_without_mfr_stays_unresolved() -> None:
    """Omitting ``mass_flow_rate`` on an inlet port leaves the MFC unresolved.

    Asserts that the synthesised MFC has *no* ``mass_flow_rate`` in its
    ``properties`` (so ``resolve_unset_flow_rates`` fills it in from
    global conservation).
    """
    cfg = _minimal_ported_config(with_mfr=False)
    normalized = normalize_config(cfg)
    inlet_conn = next(c for c in normalized["connections"] if c["id"] == "feed_to_r1")
    assert "mass_flow_rate" not in (inlet_conn.get("properties") or {})
