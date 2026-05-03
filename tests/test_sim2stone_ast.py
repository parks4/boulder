"""Unit tests for ``boulder/sim2stone_ast.py`` — Phase D AST pattern extraction.

Asserts:
- ``ct.Func1("Gaussian", [peak, center, fwhm])`` assignments are detected with
  correct params (including variable-resolved args like ``190 * 1e-21``).
- ``def mdot(t): return reactor.mass / tau_var`` + ``MassFlowController(..., mdot=mdot)``
  is detected as a residence-time closure.
- ``while reactor.T > N: sim.solve_steady(); tau *= k`` is detected as a continuation.
- ``for n in range(N): time += dt; sim.advance(time)`` is detected as ``advance_grid``
  with a ``grid:`` sub-block.
- ``while t < t_total: ... sim.advance(...) ... sim.reinitialize()`` is detected as
  ``micro_step`` with timing params.
- The public ``extract_from_source`` function returns correct results for the three
  vendored Cantera example scripts.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List

import pytest

from boulder.sim2stone_ast import (
    ASTExtractionResult,
    DetectedClosure,
    DetectedContinuation,
    DetectedSignal,
    DetectedSolver,
    _collect_scalar_assignments,
    _detect_advance_timing,
    _detect_continuation,
    _detect_func1_signals,
    _detect_residence_time_closures,
    _detect_solver_hint,
    extract_from_source,
)

import ast


_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES_DIR = _REPO_ROOT / "docs" / "cantera_examples"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(src: str) -> ast.AST:
    return ast.parse(textwrap.dedent(src))


# ---------------------------------------------------------------------------
# Scalar assignment collection
# ---------------------------------------------------------------------------


class TestCollectScalarAssignments:
    def test_simple_constants(self) -> None:
        """Scalar integer and float assignments are collected correctly."""
        tree = _parse(
            """
            EN_peak = 190 * 1e-21
            pulse_center = 24e-9
            n_steps = 300
            step_size = 4.0e-4
            """
        )
        env = _collect_scalar_assignments(tree)
        assert abs(env["EN_peak"] - 190e-21) < 1e-30
        assert env["pulse_center"] == pytest.approx(24e-9)
        assert env["n_steps"] == pytest.approx(300.0)
        assert env["step_size"] == pytest.approx(4e-4)

    def test_derived_from_prior_var(self) -> None:
        """Variable resolved from a previously defined scalar."""
        tree = _parse(
            """
            pulse_width = 3e-9
            pulse_fwhm = pulse_width * 2 * 2.0
            """
        )
        env = _collect_scalar_assignments(tree)
        assert env["pulse_fwhm"] == pytest.approx(3e-9 * 4.0)

    def test_nonscalar_ignored(self) -> None:
        """Non-scalar assignments (lists, strings) do not appear in the env."""
        tree = _parse("x = [1, 2, 3]")
        env = _collect_scalar_assignments(tree)
        assert "x" not in env


# ---------------------------------------------------------------------------
# Func1 signal detection
# ---------------------------------------------------------------------------


class TestDetectFunc1Signals:
    def test_gaussian_literal_args(self) -> None:
        """ct.Func1('Gaussian', [peak, center, fwhm]) with literal floats."""
        tree = _parse("g = ct.Func1('Gaussian', [1.9e-19, 24e-9, 7.0e-9])")
        sigs = _detect_func1_signals(tree)
        assert len(sigs) == 1
        s = sigs[0]
        assert s.signal_id == "g"
        assert s.kind == "Gaussian"
        assert s.params["peak"] == pytest.approx(1.9e-19)
        assert s.params["center"] == pytest.approx(24e-9)
        assert s.params["fwhm"] == pytest.approx(7.0e-9)
        assert s.derived_via == "ast_match"

    def test_gaussian_variable_args(self) -> None:
        """Gaussian args resolved from prior scalar assignments."""
        src = """
        EN_peak = 190 * 1e-21
        pulse_center = 24e-9
        pulse_width = 3e-9
        pulse_fwhm = pulse_width * 2 * 2.0
        gaussian_EN = ct.Func1("Gaussian", [EN_peak, pulse_center, pulse_fwhm])
        """
        tree = _parse(src)
        sigs = _detect_func1_signals(tree)
        assert len(sigs) == 1
        s = sigs[0]
        assert s.signal_id == "gaussian_EN"
        assert s.kind == "Gaussian"
        assert s.params["peak"] == pytest.approx(190e-21)
        assert s.params["center"] == pytest.approx(24e-9)

    def test_constant_func1(self) -> None:
        """ct.Func1('constant', 42.0) → Constant signal."""
        tree = _parse("c = ct.Func1('constant', [42.0])")
        sigs = _detect_func1_signals(tree)
        assert len(sigs) == 1
        s = sigs[0]
        assert s.kind == "Constant"
        assert s.params["value"] == pytest.approx(42.0)

    def test_sine_func1(self) -> None:
        """ct.Func1('sin', [2.0]) → Sine signal with frequency."""
        tree = _parse("f = ct.Func1('sin', [2.0])")
        sigs = _detect_func1_signals(tree)
        assert len(sigs) == 1
        assert sigs[0].kind == "Sine"
        assert sigs[0].params["frequency"] == pytest.approx(2.0)

    def test_unknown_kind_ignored(self) -> None:
        """Unknown ct.Func1 kinds are silently skipped."""
        tree = _parse("f = ct.Func1('weird_kind', [1.0])")
        assert _detect_func1_signals(tree) == []

    def test_non_ct_func1_ignored(self) -> None:
        """Non-ct.Func1 call-sites are not detected."""
        tree = _parse("f = SomethingElse('Gaussian', [1.0, 2.0, 3.0])")
        assert _detect_func1_signals(tree) == []


# ---------------------------------------------------------------------------
# Closure detection
# ---------------------------------------------------------------------------


class TestDetectResidenceTimeClosure:
    def test_combustor_pattern(self) -> None:
        """Combustor closure: def mdot(t): return reactor.mass / tau_var."""
        src = """
        def mdot(t):
            return combustor.mass / residence_time

        residence_time = 0.1
        inlet_mfc = ct.MassFlowController(inlet, combustor, mdot=mdot)
        """
        tree = _parse(src)
        closures = _detect_residence_time_closures(tree)
        assert len(closures) == 1
        c = closures[0]
        assert c.mfc_var == "inlet_mfc"
        assert c.reactor_var == "combustor"
        assert c.tau_var == "residence_time"
        assert c.derived_via == "ast_match"

    def test_no_closure_when_no_mfc(self) -> None:
        """No closure detected when the function is not linked to an MFC."""
        src = """
        def mdot(t):
            return r.mass / tau
        """
        tree = _parse(src)
        assert _detect_residence_time_closures(tree) == []

    def test_no_closure_when_wrong_pattern(self) -> None:
        """No closure detected for a function that does not divide by a variable."""
        src = """
        def mdot(t):
            return 1.0
        inlet_mfc = ct.MassFlowController(inlet, combustor, mdot=mdot)
        """
        tree = _parse(src)
        closures = _detect_residence_time_closures(tree)
        assert len(closures) == 0


# ---------------------------------------------------------------------------
# Continuation detection
# ---------------------------------------------------------------------------


class TestDetectContinuation:
    def test_combustor_while_loop(self) -> None:
        """while reactor.T > 500: sim.solve_steady(); tau *= 0.9 → continuation."""
        src = """
        while combustor.T > 500:
            sim.initial_time = 0.0
            sim.solve_steady()
            residence_time *= 0.9
        """
        tree = _parse(src)
        cont = _detect_continuation(tree)
        assert cont is not None
        assert cont.condition_attr == "T"
        assert cont.condition_threshold == pytest.approx(500.0)
        assert cont.tau_var == "residence_time"
        assert cont.tau_factor == pytest.approx(0.9)

    def test_no_continuation_without_solve_steady(self) -> None:
        """No continuation detected when solve_steady is absent."""
        src = """
        while r.T > 500:
            sim.advance(1.0)
        """
        tree = _parse(src)
        assert _detect_continuation(tree) is None

    def test_no_continuation_without_while(self) -> None:
        """No continuation detected without a while loop."""
        src = "sim.solve_steady()"
        tree = _parse(src)
        assert _detect_continuation(tree) is None


# ---------------------------------------------------------------------------
# Solver loop detection
# ---------------------------------------------------------------------------


class TestDetectSolverHint:
    def test_for_loop_advance_grid(self) -> None:
        """for n in range(N): sim.advance(t) → advance_grid."""
        src = """
        for n in range(300):
            time += 4e-4
            sim.advance(time)
        """
        tree = _parse(src)
        solver = _detect_solver_hint(tree)
        assert solver is not None
        assert solver.kind == "advance_grid"

    def test_while_advance_grid(self) -> None:
        """while t < total: sim.advance(t) → advance_grid (no reinitialize)."""
        src = """
        while t < t_total:
            sim.advance(t + dt)
        """
        tree = _parse(src)
        solver = _detect_solver_hint(tree)
        assert solver is not None
        assert solver.kind == "advance_grid"

    def test_while_micro_step(self) -> None:
        """while t < t_total: sim.advance(...) + sim.reinitialize() → micro_step."""
        src = """
        while t < t_total:
            sim.advance(t + dt)
            sim.reinitialize()
        """
        tree = _parse(src)
        solver = _detect_solver_hint(tree)
        assert solver is not None
        assert solver.kind == "micro_step"

    def test_advance_timing_extracted(self) -> None:
        """n_steps and step_size (from for loop AugAssign) are detected."""
        src = """
        n_steps = 300
        for n in range(n_steps):
            time += 4.0e-4
            sim.advance(time)
        """
        tree = _parse(src)
        timing = _detect_advance_timing(tree)
        assert timing["n_steps"] == pytest.approx(300.0)
        assert timing["step_size"] == pytest.approx(4e-4)

    def test_micro_step_timing_extracted(self) -> None:
        """t_total, dt_max, dt_chunk from named assignments."""
        src = """
        t_total = 90e-9
        dt_max = 1e-10
        dt_chunk = 1e-9
        while t < t_total:
            sim.advance(t + dt_max)
            sim.reinitialize()
        """
        tree = _parse(src)
        timing = _detect_advance_timing(tree)
        assert timing["t_total"] == pytest.approx(90e-9)
        assert timing["dt_max"] == pytest.approx(1e-10)
        assert timing["dt_chunk"] == pytest.approx(1e-9)


# ---------------------------------------------------------------------------
# Integration: extract_from_source on vendored scripts
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _skip_if_missing() -> None:
    """Skip integration fixture tests if cantera examples are absent."""
    pass  # Individual tests skip themselves via pytest.skip


def _examples_available() -> bool:
    return (_EXAMPLES_DIR / "nanosecond_pulse_discharge.py").is_file()


@pytest.mark.skipif(
    not _examples_available(),
    reason="docs/cantera_examples not present",
)
class TestExtractFromVendoredScripts:
    def test_nanosecond_has_gaussian_signal(self) -> None:
        """nanosecond_pulse_discharge.py → Gaussian signal detected with params."""
        result = extract_from_source(
            str(_EXAMPLES_DIR / "nanosecond_pulse_discharge.py")
        )
        assert len(result.signals) >= 1
        gauss = next((s for s in result.signals if s.kind == "Gaussian"), None)
        assert gauss is not None, "No Gaussian signal detected"
        assert "peak" in gauss.params
        assert "center" in gauss.params
        assert "fwhm" in gauss.params
        assert gauss.params["peak"] == pytest.approx(190e-21, rel=1e-3)
        assert gauss.params["center"] == pytest.approx(24e-9, rel=1e-3)

    def test_nanosecond_has_micro_step_solver(self) -> None:
        """nanosecond_pulse_discharge.py → micro_step solver detected."""
        result = extract_from_source(
            str(_EXAMPLES_DIR / "nanosecond_pulse_discharge.py")
        )
        assert result.solver is not None
        assert result.solver.kind == "micro_step"
        params = result.solver.params
        assert "t_total" in params
        assert "dt_chunk" in params
        assert "dt_max" in params

    def test_nanosecond_has_efield_binding(self) -> None:
        """nanosecond_pulse_discharge.py → reduced_electric_field binding detected."""
        result = extract_from_source(
            str(_EXAMPLES_DIR / "nanosecond_pulse_discharge.py")
        )
        assert len(result.bindings) >= 1
        binding = result.bindings[0]
        assert "reduced_electric_field" in binding.target
        assert binding.signal_id == "gaussian_EN"

    def test_combustor_has_closure(self) -> None:
        """combustor.py → residence-time closure detected."""
        result = extract_from_source(str(_EXAMPLES_DIR / "combustor.py"))
        assert len(result.closures) == 1
        c = result.closures[0]
        assert c.reactor_var == "combustor"
        assert c.tau_var == "residence_time"

    def test_combustor_has_continuation(self) -> None:
        """combustor.py → while T > 500 continuation detected."""
        result = extract_from_source(str(_EXAMPLES_DIR / "combustor.py"))
        assert len(result.continuations) == 1
        cont = result.continuations[0]
        assert cont.condition_attr == "T"
        assert cont.condition_threshold == pytest.approx(500.0)
        assert cont.tau_var == "residence_time"
        assert cont.tau_factor == pytest.approx(0.9)

    def test_reactor2_has_advance_grid_solver(self) -> None:
        """reactor2.py → advance_grid solver with n_steps and step_size detected."""
        result = extract_from_source(str(_EXAMPLES_DIR / "reactor2.py"))
        assert result.solver is not None
        assert result.solver.kind == "advance_grid"
        assert "n_steps" in result.solver.params
        assert result.solver.params["n_steps"] == pytest.approx(300.0)
        assert "step_size" in result.solver.params
        assert result.solver.params["step_size"] == pytest.approx(4e-4)

    def test_reactor2_has_no_signals(self) -> None:
        """reactor2.py uses no ct.Func1 signals."""
        result = extract_from_source(str(_EXAMPLES_DIR / "reactor2.py"))
        assert result.signals == []
        assert result.bindings == []

    def test_nonexistent_file_returns_empty(self) -> None:
        """extract_from_source on a missing file returns empty result."""
        result = extract_from_source("/does/not/exist.py")
        assert result.signals == []
        assert result.closures == []
        assert result.continuations == []
        assert result.solver is None
