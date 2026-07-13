"""Regression test: a Gaussian-pulse MFC round-trips through STONE correctly.

It must become a real schedule, not a frozen t=0 snapshot.

Bug: mfc.mass_flow_rate always reads back as the evaluated float at the
network's current time (Cantera never returns the underlying Func1 object),
so sim2stone's device-introspection pass could only snapshot whatever value
happened to be current when the object was read -- discarding the pulse
shape entirely (e.g. upstream's fuel_injection.py Gaussian fuel pulse,
centered at t=2s with std_dev=0.5s, snapshotted near t=0 collapses to a tiny
tail value ~1/1000th of the intended flow).
"""

from __future__ import annotations

import os
import tempfile
import textwrap

import pytest

from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.sim2stone import sim_to_stone_yaml


def _write_and_run(python_content: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(textwrap.dedent(python_content))
        f.flush()
        temp_name = f.name

    try:
        exec_globals: dict = {}
        with open(temp_name, "r") as file:
            exec(file.read(), exec_globals)
        sim = exec_globals["sim"]
        return sim_to_stone_yaml(
            sim,
            default_mechanism="h2o2.yaml",
            source_file=temp_name,
            include_comments=False,
        )
    finally:
        os.unlink(temp_name)


def test_gaussian_mfc_gets_real_schedule_not_snapshot() -> None:
    """A lone Func1-Gaussian MFC's mass_flow_rate becomes a schedule dict."""
    yaml_str = _write_and_run(
        """
        import cantera as ct

        gas = ct.Solution("h2o2.yaml")
        gas.TPX = 300.0, ct.one_atm, "H2:1, N2:1"
        inlet = ct.Reservoir(gas, name="inlet")

        gas.TP = 900.0, ct.one_atm
        r = ct.IdealGasReactor(gas, name="reactor")
        r.volume = 1e-3

        total_mass = 3.0e-3
        std_dev = 0.5
        center_time = 2.0
        amplitude = total_mass / (std_dev * (2 * 3.141592653589793) ** 0.5)
        fwhm = std_dev * 2 * (2 * 0.6931471805599453) ** 0.5
        pulse = ct.Func1("Gaussian", [amplitude, center_time, fwhm])

        ct.MassFlowController(inlet, r, mdot=pulse, name="fuel_mfc")
        sim = ct.ReactorNet([r])
        """
    )

    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))
    (mfc,) = [c for c in normalized["connections"] if c["id"] == "fuel_mfc"]
    mfr = mfc["properties"]["mass_flow_rate"]

    assert isinstance(mfr, dict), f"expected a schedule dict, got {mfr!r}"
    assert mfr["func"] == "Gaussian"
    assert mfr["args"][1] == pytest.approx(2.0)  # center_time survives intact
    assert mfr["args"][2] == pytest.approx(1.1774100225154747, rel=1e-6)  # fwhm

    # The top-level signals: block should carry the same AST-recovered signal.
    assert "signals" in normalized
    assert any("Gaussian" in s for s in normalized["signals"])


def test_gaussian_signal_bound_elsewhere_is_not_reused_for_mfc() -> None:
    """A Gaussian already claimed by another binding must not be reused.

    It must not also be misapplied to an unrelated MFC in the same network.
    """
    yaml_str = _write_and_run(
        """
        import cantera as ct

        EN_peak = 1e-19
        pulse_center = 24e-9
        pulse_fwhm = 7e-9
        gaussian_EN = ct.Func1("Gaussian", [EN_peak, pulse_center, pulse_fwhm])

        gas = ct.Solution("h2o2.yaml")
        gas.TPX = 300.0, ct.one_atm, "H2:1, N2:1"
        try:
            # h2o2.yaml is an ideal-gas phase, not plasma -- this raises at
            # runtime. The AST-based binding detector reads source text
            # independently of execution, so the assignment still needs to
            # be *present* here without aborting the rest of the script.
            gas.reduced_electric_field = gaussian_EN(0.0)
        except Exception:
            pass

        inlet = ct.Reservoir(gas, name="inlet")
        r = ct.IdealGasReactor(gas, name="reactor")
        r.volume = 1e-3
        ct.MassFlowController(inlet, r, mdot=0.01, name="steady_mfc")
        sim = ct.ReactorNet([r])
        """
    )

    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))
    (mfc,) = [c for c in normalized["connections"] if c["id"] == "steady_mfc"]
    mfr = mfc["properties"]["mass_flow_rate"]
    # Plain constant mdot -- must stay a scalar, not get hijacked into the
    # unrelated plasma Gaussian's schedule.
    assert isinstance(mfr, (int, float))
