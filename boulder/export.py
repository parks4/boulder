"""Boulder export helpers.

Provides :func:`points_from_streams` for extracting P&ID stream-point data
from a post-solve config, intended for use in Excel Calculation Note "Points"
sheets or other structured report outputs.

Design principle — Points vs. Reactor properties
-------------------------------------------------
In a P&ID context, **stream points** (diamonds) represent the boundary
conditions between process units: temperature, pressure, mass flow rate,
composition, and derived thermo properties at the handoff between stages.
They are NOT reactor properties.

The "Points" export (`points_from_streams`) therefore covers **only**
nodes whose ``properties.stream_point == true``, i.e. the boundary
reservoirs synthesised by the staged solver at each inter-stage connection.
It does **not** export operating conditions of reactor nodes (PSR, PFR,
Torch) — those belong to separate reactor-level reports (e.g. temperature
and mole-fraction profiles on the detail or thermo sheets).

Concretely:

- ``points_from_streams`` → inlet/outlet stream conditions (boundary).
- Reactor thermo sheets → T, Y, conversion profiles inside each unit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .cantera_converter import DualCanteraConverter


def points_from_streams(
    config: Dict[str, Any],
    converter: Optional["DualCanteraConverter"] = None,
) -> List[Dict[str, Any]]:
    """Return one dict per stream-point diamond from the post-solve config.

    A stream-point is a node whose properties carry ``stream_point: true``.
    After :func:`~boulder.staged_solver.solve_staged` runs with
    ``stream_reservoirs=True``, each such node has its properties enriched
    with the full P&ID stream snapshot: T, P, top_Y, mdot, h_mass, density,
    and volumetric flow rates.

    This is the single source of truth for the "Points" section of the
    Calculation Note.  The caller (e.g. the Excel builder) receives a list of
    dicts that can be written as rows — one row per stream point.

    Parameters
    ----------
    config :
        Normalized, post-solve config dict (from ``runner.config`` or
        ``simulation_worker.progress.config``).
    converter :
        Optional :class:`~boulder.cantera_converter.DualCanteraConverter`.
        When provided, any stream-point thermo not yet in ``config["nodes"]``
        is read from ``converter.reactor_meta``.

    Returns
    -------
    list of dict
        Each dict has keys::

            id          – stream-point node id (e.g. "psr_outlet")
            source_node – id of the upstream reactor
            target_nodes – list of downstream reactor ids
            T_K         – temperature [K]
            T_C         – temperature [°C]
            P_Pa        – pressure [Pa]
            P_bar       – pressure [bar]
            mdot_kg_s   – mass flow rate [kg/s]
            h_mass_J_kg – specific enthalpy [J/kg]
            density_kg_m3 – density [kg/m³]
            v_dot_normal_m3_h – normal volumetric flow [Nm³/h]
            v_dot_real_m3_h   – real volumetric flow [m³/h]
            top_Y       – dict of top-3 species mass fractions
    """
    points: List[Dict[str, Any]] = []

    for node in config.get("nodes") or []:
        props = node.get("properties") or {}
        meta = node.get("metadata") or {}

        is_stream = props.get("stream_point") or meta.get("stream_point")
        if not is_stream:
            continue

        nid = node["id"]

        # Prefer properties (populated by _update_stream_point via back-fill).
        # Fall back to converter.reactor_meta when available.
        if converter is not None:
            rm = converter.reactor_meta.get(nid) or {}
        else:
            rm = {}

        T_K = float(props.get("temperature") or rm.get("T") or 0.0)
        P_Pa = float(props.get("pressure") or rm.get("P") or 0.0)
        mdot = float(props.get("mdot") or rm.get("mdot") or 0.0)
        h_mass = float(props.get("h_mass") or rm.get("h_mass") or 0.0)
        density = float(props.get("density") or rm.get("density") or 0.0)
        v_dot_norm = float(props.get("v_dot_normal_m3_h") or 0.0)
        v_dot_real = float(props.get("v_dot_real_m3_h") or 0.0)
        top_Y: Dict[str, float] = {}
        raw_top_Y = props.get("top_Y") or rm.get("top_Y") or {}
        if isinstance(raw_top_Y, dict):
            top_Y = {str(k): float(v) for k, v in raw_top_Y.items()}

        # Resolve target_nodes from node properties / connections
        target_nodes: List[str] = []
        raw_tgt = props.get("target_nodes") or meta.get("target_nodes") or []
        if isinstance(raw_tgt, list):
            target_nodes = [str(t) for t in raw_tgt]
        elif props.get("target_node"):
            target_nodes = [str(props["target_node"])]

        # Fall back: scan connections whose source is this stream point
        if not target_nodes:
            for conn in config.get("connections") or []:
                if conn.get("source") == nid:
                    target_nodes.append(str(conn.get("target", "")))

        points.append(
            {
                "id": nid,
                "source_node": str(props.get("source_node") or meta.get("source_node") or ""),
                "target_nodes": target_nodes,
                "T_K": T_K,
                "T_C": T_K - 273.15,
                "P_Pa": P_Pa,
                "P_bar": P_Pa / 1e5,
                "mdot_kg_s": mdot,
                "h_mass_J_kg": h_mass,
                "density_kg_m3": density,
                "v_dot_normal_m3_h": v_dot_norm,
                "v_dot_real_m3_h": v_dot_real,
                "top_Y": top_Y,
            }
        )

    return points
