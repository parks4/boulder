"""PSR volume sizing from t_res_s in Boulder core.

Asserts that:
- Volume from t_res_s yields hydraulic residence time m/mdot ≈ t_res_s at sizing.
- No spurious /1000 factor in V = tau * mdot / rho.
- Resolved MFC rates from flow conservation are used, not YAML-only lookup.
- Explicit volume: skips t_res_s sizing.
- Zero incoming mdot with t_res_s raises a clear ValueError.
"""

from __future__ import annotations

import cantera as ct
import pytest

from boulder.cantera_converter import DualCanteraConverter, resolve_unset_flow_rates
from boulder.reactor_sizing import (
    apply_residence_time_volumes,
    resolve_volume_from_t_res_s,
    sum_incoming_mdot,
)

_MECH = "gri30.yaml"
_T_RES = 1.0e-3
_MDOT = 2.0e-3


def _gas_at(T: float = 1500.0) -> ct.Solution:
    gas = ct.Solution(_MECH)
    gas.TPX = T, 101325.0, "N2:1"
    return gas


def _wire_open_psr(
    conv: DualCanteraConverter,
    *,
    mdot_in: float | None = _MDOT,
    mdot_out_resolved: bool = False,
) -> None:
    """Register inlet → PSR → outlet with optional conservation-resolved outlet."""
    gas = _gas_at()
    inlet = ct.Reservoir(gas)
    psr_gas = ct.Solution(_MECH)
    psr_gas.TPX = gas.T, gas.P, gas.X
    psr = ct.IdealGasConstPressureMoleReactor(psr_gas, name="psr")
    outlet = ct.Reservoir(gas)

    conv.reactors["inlet"] = inlet
    conv.reactors["psr"] = psr
    conv.reactors["outlet"] = outlet

    mfc_in = ct.MassFlowController(inlet, psr)
    if mdot_in is not None:
        mfc_in.mass_flow_rate = mdot_in
        conv._mfc_flow_rates["inlet_to_psr"] = mdot_in
    else:
        conv._unresolved_mfc_ids.add("inlet_to_psr")

    conv.connections["inlet_to_psr"] = mfc_in
    conv._mfc_topology["inlet_to_psr"] = ("inlet", "psr")

    mfc_out = ct.MassFlowController(psr, outlet)
    conv.connections["psr_to_outlet"] = mfc_out
    conv._mfc_topology["psr_to_outlet"] = ("psr", "outlet")
    if mdot_out_resolved:
        conv._unresolved_mfc_ids.add("psr_to_outlet")
    else:
        mfc_out.mass_flow_rate = mdot_in if mdot_in is not None else _MDOT
        conv._mfc_flow_rates["psr_to_outlet"] = float(mdot_in or _MDOT)

    if conv._unresolved_mfc_ids:
        all_mfcs = {
            cid: dev
            for cid, dev in conv.connections.items()
            if isinstance(dev, ct.MassFlowController)
        }
        resolve_unset_flow_rates(
            conv._mfc_topology,
            conv._mfc_flow_rates,
            all_mfcs,
            conv.reactors,
            conv._unresolved_mfc_ids,
        )


class TestResolveVolumeFromTRes:
    def test_volume_from_t_res_matches_tau(self):
        """After sizing, m/mdot equals t_res_s within relative tolerance."""
        conv = DualCanteraConverter(_MECH)
        _wire_open_psr(conv)
        nodes = [{"id": "psr", "properties": {"t_res_s": _T_RES}}]
        apply_residence_time_volumes(conv, nodes)

        psr = conv.reactors["psr"]
        mdot = sum_incoming_mdot(conv, "psr")
        tau = psr.mass / mdot
        assert tau == pytest.approx(_T_RES, rel=1e-6)

    def test_no_spurious_1000_factor(self):
        """Volume equals t_res * mdot / rho, not divided by 1000."""
        conv = DualCanteraConverter(_MECH)
        _wire_open_psr(conv)
        psr = conv.reactors["psr"]
        rho = float(psr.phase.density)
        expected_v = _T_RES * _MDOT / rho

        apply_residence_time_volumes(
            conv, [{"id": "psr", "properties": {"t_res_s": _T_RES}}]
        )
        assert psr.volume == pytest.approx(expected_v, rel=1e-9)
        wrong_v = _T_RES * _MDOT / rho / 1000.0
        assert psr.volume != pytest.approx(wrong_v, rel=1e-3)

    def test_uses_resolved_mdot_not_yaml_only(self):
        """Conservation-resolved outlet MFC still sizes volume from inlet mdot."""
        conv = DualCanteraConverter(_MECH)
        _wire_open_psr(conv, mdot_out_resolved=True)
        mdot = sum_incoming_mdot(conv, "psr")
        assert mdot == pytest.approx(_MDOT, rel=1e-9)

        apply_residence_time_volumes(
            conv, [{"id": "psr", "properties": {"t_res_s": _T_RES}}]
        )
        psr = conv.reactors["psr"]
        assert psr.mass / mdot == pytest.approx(_T_RES, rel=1e-6)

    def test_explicit_volume_skips_t_res(self):
        """When volume is set in node properties, t_res_s does not overwrite it."""
        conv = DualCanteraConverter(_MECH)
        _wire_open_psr(conv)
        fixed_v = 3.5e-5
        conv.reactors["psr"].volume = fixed_v

        apply_residence_time_volumes(
            conv,
            [{"id": "psr", "properties": {"t_res_s": _T_RES, "volume": fixed_v}}],
        )
        assert conv.reactors["psr"].volume == fixed_v

    def test_zero_mdot_raises(self):
        """t_res_s with no incoming flow raises ValueError."""
        conv = DualCanteraConverter(_MECH)
        gas = _gas_at()
        psr = ct.IdealGasConstPressureMoleReactor(gas, name="psr")
        conv.reactors["psr"] = psr

        with pytest.raises(ValueError, match="no positive incoming"):
            resolve_volume_from_t_res_s(psr, _T_RES, 0.0)
