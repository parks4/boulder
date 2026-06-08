"""Residence-time-based reactor volume sizing for Boulder networks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import cantera as ct

if TYPE_CHECKING:
    from .cantera_converter import DualCanteraConverter


def sum_incoming_mdot(converter: "DualCanteraConverter", reactor_id: str) -> float:
    """Sum resolved inlet mass flow rates [kg/s] for *reactor_id*."""
    total = 0.0
    for cid, (_src, tgt) in converter._mfc_topology.items():
        if tgt != reactor_id:
            continue
        rate = converter._mfc_flow_rates.get(cid)
        if rate is not None and float(rate) > 0.0:
            total += float(rate)
    return total


def resolve_volume_from_t_res_s(
    reactor: ct.ReactorBase,
    t_res_s: float,
    mdot_in: float,
) -> float:
    r"""Return reactor volume [m³] so that τ ≈ t_res_s at the current density.

    Uses :math:`V = t_{res} \\dot m / \\rho` with :math:`\\rho` from
    ``reactor.phase.density`` at sizing time.
    """
    if t_res_s <= 0.0:
        raise ValueError(f"t_res_s must be positive, got {t_res_s}")
    if mdot_in <= 0.0:
        raise ValueError(
            "Cannot size reactor volume from residence time: no positive incoming "
            f"mass flow (mdot_in={mdot_in} kg/s)."
        )
    rho = max(float(reactor.phase.density), 1e-12)
    return max(t_res_s * mdot_in / rho, 1e-12)


def apply_residence_time_volumes(
    converter: "DualCanteraConverter",
    nodes: List[Dict[str, Any]],
    *,
    code_lines: Optional[List[str]] = None,
    var_name: Optional[Callable[[str], str]] = None,
) -> None:
    """Set ``reactor.volume`` from ``t_res_s`` on nodes that lack explicit ``volume``."""
    for node in nodes:
        rid = node["id"]
        props = node.get("properties") or {}
        if props.get("volume") is not None:
            continue
        t_res_raw = props.get("t_res_s")
        if t_res_raw is None:
            continue
        t_res_s = float(t_res_raw)
        if t_res_s <= 0.0:
            continue

        reactor = converter.reactors.get(rid)
        if reactor is None or isinstance(reactor, ct.Reservoir):
            continue

        mdot_in = sum_incoming_mdot(converter, rid)
        volume = resolve_volume_from_t_res_s(reactor, t_res_s, mdot_in)
        reactor.volume = volume

        meta = converter.reactor_meta.setdefault(rid, {})
        meta["t_res_s"] = t_res_s
        meta["volume_m3"] = volume
        meta["mdot_in_kg_s"] = mdot_in

        if code_lines is not None and var_name is not None:
            python_var = var_name(rid)
            code_lines.append(
                f"{python_var}.volume = {volume!r}  # from t_res_s={t_res_s} s"
            )
