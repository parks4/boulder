"""Systematic verification: Boulder's converted output vs. direct upstream physics.

``test_fixture_scripts_sim2stone.py`` checks that sim2stone produces valid STONE
YAML and that a downloaded script *runs without error* -- neither ever compares
actual numbers. That gap let real bugs through silently: sim2stone snapshotting
a Wall's ``heat_rate`` or a Gaussian MFC's ``mass_flow_rate`` at whatever instant
they were introspected produced YAML that validated fine and ran fine, while
completely discarding the dynamics the upstream examples exist to demonstrate
(see the git history around ``sim2stone.py``'s Wall/Gaussian-MFC handling).

This module closes that gap for two vendored examples: it runs the *true*
upstream script directly (its own transient loop, unmodified) to get a ground
truth trajectory, separately builds the equivalent network through
``sim2stone`` + Boulder's runtime from a sim2stone-friendly adapter (a script
that stops before its own transient loop so introspection captures true
initial conditions rather than a completed run's end state -- the same
adapter pattern boulder_examples uses), and asserts the two trajectories
agree on the physically meaningful signature: real oscillation for
periodic_cstr, real pollutant-precursor formation for fuel_injection.
"""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path

import numpy as np
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.sim2stone import sim_to_stone_yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / "docs" / "cantera_examples"


def _exec_vendored_script(name: str, stop_before: str) -> dict:
    """Run a vendored upstream script's own transient loop; return its globals.

    Truncates the source at *stop_before* (a line prefix) so the plotting
    section -- species-alias-indexed SolutionArray access that raises
    "cannot resize an array that references or is referenced by another
    array" when exec'd outside the script's own `__main__` run -- never
    executes. Only the network build + transient loop is needed here.
    """
    script = _EXAMPLES_DIR / name
    if not script.is_file():
        pytest.skip(f"{name} not found under docs/cantera_examples")
    os.environ.setdefault("MPLBACKEND", "Agg")
    lines = script.read_text(encoding="utf-8").splitlines()
    cut = next(i for i, line in enumerate(lines) if line.startswith(stop_before))
    source = "\n".join(lines[:cut])
    exec_globals: dict = {"__name__": "__main__"}
    exec(compile(source, str(script), "exec"), exec_globals)
    return exec_globals


def _sim2stone_yaml_from_source(source: str, mechanism: str) -> str:
    """Exec an adapter-style source string; convert the resulting sim to STONE."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(textwrap.dedent(source))
        f.flush()
        temp_name = f.name
    try:
        exec_globals: dict = {}
        exec(
            compile(Path(temp_name).read_text(encoding="utf-8"), temp_name, "exec"),
            exec_globals,
        )
        sim = exec_globals["sim"]
        return sim_to_stone_yaml(
            sim,
            default_mechanism=mechanism,
            source_file=temp_name,
            include_comments=False,
        )
    finally:
        os.unlink(temp_name)


def test_periodic_cstr_boulder_reproduces_upstream_oscillation() -> None:
    """Boulder's converted+run periodic_cstr must oscillate like the real script.

    Regression guard for the Wall heat_transfer_coeff snapshot bug: sim2stone
    used to freeze the wall's instantaneous heat_rate (~0, since both sides
    start at the same temperature) instead of recognizing the dynamic U/A
    coupling, silently turning the oscillation into a flat line.
    """
    upstream_globals = _exec_vendored_script(
        "periodic_cstr.py", stop_before="aliases = {"
    )
    states = upstream_globals["states"]
    upstream_h2 = states.X[:, states.species_names.index("H2")]
    assert upstream_h2.max() - upstream_h2.min() > 0.3, (
        "sanity check: the true upstream script itself should show a large "
        "H2 mole-fraction swing -- if this fails, the vendored copy or "
        "mechanism drifted from what this test assumes"
    )

    # Adapter: same network as periodic_cstr.py, without the transient loop,
    # so sim2stone introspects true initial conditions (mirrors
    # boulder_examples/adapters/periodic_cstr.py).
    yaml_str = _sim2stone_yaml_from_source(
        """
        import cantera as ct

        gas = ct.Solution("h2o2.yaml")
        p = 60.0 * 133.3
        t = 770.0
        gas.TPX = t, p, "H2:2, O2:1"

        upstream = ct.Reservoir(gas)
        cstr = ct.IdealGasReactor(gas)
        cstr.volume = 10.0 * 1.0e-6
        env = ct.Reservoir(gas)
        ct.Wall(cstr, env, A=1.0, U=0.02)

        sccm = 1.25
        vdot = sccm * 1.0e-6 / 60.0 * ((ct.one_atm / gas.P) * (gas.T / 273.15))
        mdot = gas.density * vdot
        ct.MassFlowController(upstream, cstr, mdot=mdot)

        downstream = ct.Reservoir(gas)
        ct.Valve(cstr, downstream, K=1.0e-9)

        network = ct.ReactorNet([cstr])
        sim = network

        # Preserve the advance-grid pattern for sim2stone's AST solver-hint
        # detector (reads source text only; never executed) so it infers
        # solver.kind: advance_grid with the true stop/dt instead of falling
        # back to advance_to_steady_state, which never converges for this
        # genuinely oscillating system.
        if False:  # pragma: no cover
            t = 0.0
            dt = 0.1
            while t < 300.0:
                t += dt
                network.advance(t)
        """,
        mechanism="h2o2.yaml",
    )
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))
    wall = next(c for c in normalized["connections"] if c["type"] == "Wall")
    assert wall["properties"].get("heat_transfer_coeff") == pytest.approx(0.02), (
        "Wall's U coefficient must survive conversion, not collapse to an "
        "electric_power_kW snapshot"
    )

    conv = DualCanteraConverter(mechanism="h2o2.yaml")
    conv.build_network(normalized)
    solver = normalized["settings"]["solver"]
    results, _ = conv.run_streaming_simulation(
        simulation_time=solver["grid"]["stop"],
        time_step=solver["grid"]["dt"],
        config=normalized,
    )
    (reactor_id,) = [
        rid
        for rid, node in [(n["id"], n) for n in normalized["nodes"]]
        if node["type"] == "IdealGasReactor"
    ]
    boulder_h2 = np.array(results["reactors"][reactor_id]["X"]["H2"])

    assert boulder_h2.max() - boulder_h2.min() > 0.3, (
        f"Boulder's periodic_cstr trajectory should oscillate like upstream's "
        f"(range={boulder_h2.max() - boulder_h2.min():.3f}); a near-zero range "
        f"means the Wall's dynamic heat transfer was lost in conversion"
    )
    # Same order of magnitude peak-to-peak swing as the true upstream run.
    assert boulder_h2.max() == pytest.approx(upstream_h2.max(), abs=0.05)
    assert boulder_h2.min() == pytest.approx(upstream_h2.min(), abs=0.05)


def test_fuel_injection_boulder_reproduces_upstream_pah_formation() -> None:
    """Boulder's converted+run fuel_injection must form real PAH precursors.

    Regression guard for the Gaussian MFC snapshot bug: sim2stone used to
    read mfc.mass_flow_rate (always the evaluated float at whatever instant
    it was introspected, never the underlying Func1) and bake that single
    value in, collapsing a 3g fuel pulse centered at t=2s into a ~1/1000th
    trickle when introspected near t=0.
    """
    upstream_globals = _exec_vendored_script(
        "fuel_injection.py", stop_before="species_aliases = {"
    )
    states = upstream_globals["states"]
    upstream_names = states.species_names
    upstream_a1 = states.X[:, upstream_names.index("A1")]  # benzene
    assert upstream_a1.max() > 1e-6, (
        "sanity check: the true upstream script itself should form a real "
        "amount of benzene (A1) -- if this fails, the vendored copy or "
        "mechanism drifted from what this test assumes"
    )

    # Adapter: same network as fuel_injection.py, Gaussian built from
    # module-level scalars (not a helper function with default args) so
    # sim2stone's AST matcher can resolve peak/center/fwhm (mirrors
    # boulder_examples/adapters/fuel_injection.py).
    yaml_str = _sim2stone_yaml_from_source(
        """
        import cantera as ct
        import numpy as np

        gas = ct.Solution("nDodecane_Reitz.yaml", "nDodecane_IG")
        gas.case_sensitive_species_names = True

        gas.TPX = 300, 20 * ct.one_atm, "c12h26:1.0"
        inlet = ct.Reservoir(gas)

        gas.TP = 1000, 20 * ct.one_atm
        gas.set_equivalence_ratio(0.30, "c12h26", "n2:3.76, o2:1.0")
        gas.equilibrate("HP")
        r = ct.IdealGasReactor(gas)
        r.volume = 0.001

        total_mass = 3.0e-3
        std_dev = 0.5
        center_time = 2.0
        fuel_amplitude = total_mass / (std_dev * np.sqrt(2 * np.pi))
        fuel_fwhm = std_dev * 2 * np.sqrt(2 * np.log(2))
        fuel_gaussian = ct.Func1("Gaussian", [fuel_amplitude, center_time, fuel_fwhm])

        ct.MassFlowController(inlet, r, mdot=fuel_gaussian)
        sim = ct.ReactorNet([r])

        tfinal = 10.0

        # Preserve the advance-grid pattern for sim2stone's AST solver-hint
        # detector (reads source text only; never executed).
        if False:  # pragma: no cover
            tnow = 0.0
            dt = 0.01
            while tnow < tfinal:
                tnow = sim.advance(tnow + dt)
        """,
        mechanism="nDodecane_Reitz.yaml",
    )
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))
    (mfc,) = [c for c in normalized["connections"] if c["type"] == "MassFlowController"]
    mfr = mfc["properties"]["mass_flow_rate"]
    assert isinstance(mfr, dict) and mfr.get("func") == "Gaussian", (
        f"MFC mass_flow_rate must be a recovered Gaussian schedule, not a "
        f"frozen snapshot: got {mfr!r}"
    )

    conv = DualCanteraConverter(mechanism=normalized["phases"]["gas"]["mechanism"])
    conv.build_network(normalized)
    solver = normalized["settings"]["solver"]
    results, _ = conv.run_streaming_simulation(
        simulation_time=solver["grid"]["stop"],
        time_step=solver["grid"]["dt"],
        config=normalized,
    )
    (reactor_id,) = [
        rid
        for rid, node in [(n["id"], n) for n in normalized["nodes"]]
        if node["type"] == "IdealGasReactor"
    ]
    boulder_a1 = np.array(results["reactors"][reactor_id]["X"]["A1"])

    assert boulder_a1.max() > 1e-6, (
        f"Boulder's fuel_injection trajectory should form real benzene (A1) "
        f"like upstream's (got max={boulder_a1.max():.3e}); a near-zero max "
        f"means the Gaussian fuel pulse was lost in conversion"
    )
    # Same order of magnitude peak as the true upstream run (PAH formation is
    # extremely sensitive to the pulse shape, so this is a loose check).
    ratio = boulder_a1.max() / upstream_a1.max()
    assert 0.1 < ratio < 10.0, (
        f"Boulder's peak A1 ({boulder_a1.max():.3e}) should be within an "
        f"order of magnitude of upstream's ({upstream_a1.max():.3e}), "
        f"ratio={ratio:.3f}"
    )
