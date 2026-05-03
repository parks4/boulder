"""Tests for boulder/signals.py — signal registry (Phase A).

Asserts:
- Each primitive source kind (Constant, Sine, Gaussian, Step, Ramp,
  PiecewiseLinear, FromCSV) builds a correct callable/Func1 and evaluates
  to the expected value at known time points.
- Combinator kinds (Sum, Gain, Integrator) resolve prior signals and produce
  correct values.
- build_signal_registry builds an ordered dict of all named signals from a
  signals block.
"""

import math
import os
import tempfile

import cantera as ct
import pytest

from boulder.signals import build_signal, build_signal_registry


# ---------------------------------------------------------------------------
# Primitive sources
# ---------------------------------------------------------------------------


class TestConstant:
    def test_constant_returns_fixed_value(self):
        """Constant signal evaluates to value at any time."""
        sig = build_signal({"id": "c", "Constant": {"value": 3.14}})
        assert sig(0.0) == pytest.approx(3.14)
        assert sig(99.9) == pytest.approx(3.14)

    def test_constant_zero(self):
        """Constant signal evaluates to 0 when value is 0."""
        sig = build_signal({"Constant": {"value": 0.0}})
        assert sig(5.0) == pytest.approx(0.0)


class TestSine:
    def test_sine_at_zero(self):
        """Sine signal is zero at t=0 when phase and offset are 0."""
        sig = build_signal({"Sine": {"amplitude": 1.0, "frequency": 1.0}})
        assert sig(0.0) == pytest.approx(0.0, abs=1e-12)

    def test_sine_at_quarter_period(self):
        """Sine signal is amplitude at t = 1/(4f)."""
        sig = build_signal({"Sine": {"amplitude": 5.0, "frequency": 2.0}})
        assert sig(1.0 / (4 * 2.0)) == pytest.approx(5.0, rel=1e-9)

    def test_sine_with_offset(self):
        """Sine signal offset shifts the value at all times."""
        sig = build_signal({"Sine": {"amplitude": 0.0, "frequency": 1.0, "offset": 7.5}})
        assert sig(0.0) == pytest.approx(7.5)
        assert sig(0.25) == pytest.approx(7.5)


class TestGaussian:
    def test_gaussian_returns_func1(self):
        """Gaussian signal returns a ct.Func1 object."""
        sig = build_signal({"Gaussian": {"peak": 1.9e-19, "center": 24e-9, "fwhm": 7.06e-9}})
        assert isinstance(sig, ct.Func1)

    def test_gaussian_peak_at_center(self):
        """Gaussian signal evaluates to peak at center time."""
        peak = 1.9e-19
        center = 24e-9
        fwhm = 7.06e-9
        sig = build_signal({"Gaussian": {"peak": peak, "center": center, "fwhm": fwhm}})
        assert sig(center) == pytest.approx(peak, rel=1e-6)

    def test_gaussian_zero_far_from_center(self):
        """Gaussian signal is near zero far from center."""
        sig = build_signal({"Gaussian": {"peak": 1.0, "center": 0.0, "fwhm": 1e-9}})
        assert abs(sig(1.0)) < 1e-10


class TestStep:
    def test_step_before_transition(self):
        """Step signal returns value_before for t < t_step."""
        sig = build_signal({"Step": {"t_step": 1.0, "value_before": 0.0, "value_after": 5.0}})
        assert sig(0.5) == pytest.approx(0.0)

    def test_step_at_transition(self):
        """Step signal returns value_after at t == t_step."""
        sig = build_signal({"Step": {"t_step": 1.0, "value_before": 0.0, "value_after": 5.0}})
        assert sig(1.0) == pytest.approx(5.0)

    def test_step_after_transition(self):
        """Step signal returns value_after for t > t_step."""
        sig = build_signal({"Step": {"t_step": 1.0, "value_before": 0.0, "value_after": 5.0}})
        assert sig(2.0) == pytest.approx(5.0)


class TestRamp:
    def test_ramp_before_start(self):
        """Ramp signal returns value_start before t_start."""
        sig = build_signal({"Ramp": {"t_start": 1.0, "t_end": 3.0, "value_start": 0.0, "value_end": 10.0}})
        assert sig(0.0) == pytest.approx(0.0)

    def test_ramp_midpoint(self):
        """Ramp signal returns midpoint value at midpoint time."""
        sig = build_signal({"Ramp": {"t_start": 0.0, "t_end": 2.0, "value_start": 0.0, "value_end": 10.0}})
        assert sig(1.0) == pytest.approx(5.0)

    def test_ramp_after_end(self):
        """Ramp signal returns value_end after t_end."""
        sig = build_signal({"Ramp": {"t_start": 1.0, "t_end": 3.0, "value_start": 0.0, "value_end": 10.0}})
        assert sig(5.0) == pytest.approx(10.0)

    def test_ramp_invalid_times_raises(self):
        """Ramp signal raises ValueError when t_end <= t_start."""
        with pytest.raises(ValueError, match="t_end"):
            build_signal({"Ramp": {"t_start": 3.0, "t_end": 1.0, "value_start": 0.0, "value_end": 1.0}})


class TestPiecewiseLinear:
    def test_piecewise_linear_returns_func1(self):
        """PiecewiseLinear signal returns a ct.Func1 object."""
        sig = build_signal({"PiecewiseLinear": {"points": [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]]}})
        assert isinstance(sig, ct.Func1)

    def test_piecewise_linear_at_known_point(self):
        """PiecewiseLinear signal interpolates correctly at a known point."""
        sig = build_signal({"PiecewiseLinear": {"points": [[0.0, 0.0], [1.0, 10.0]]}})
        assert sig(0.5) == pytest.approx(5.0, rel=1e-6)

    def test_piecewise_linear_too_few_points(self):
        """PiecewiseLinear with fewer than 2 points raises ValueError."""
        with pytest.raises(ValueError, match="at least 2 points"):
            build_signal({"PiecewiseLinear": {"points": [[0.0, 1.0]]}})


class TestFromCSV:
    def test_from_csv_reads_file(self, tmp_path):
        """FromCSV signal reads a CSV file and returns a ct.Func1."""
        csv_file = tmp_path / "signal.csv"
        csv_file.write_text("t,value\n0.0,0.0\n1.0,10.0\n2.0,5.0\n")
        sig = build_signal({"FromCSV": {"path": str(csv_file)}})
        assert isinstance(sig, ct.Func1)
        assert sig(0.5) == pytest.approx(5.0, rel=1e-6)

    def test_from_csv_missing_column_raises(self, tmp_path):
        """FromCSV signal raises ValueError when a column is missing."""
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("time,val\n0.0,1.0\n1.0,2.0\n")
        with pytest.raises(ValueError, match="missing column"):
            build_signal({"FromCSV": {"path": str(csv_file)}})


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------


class TestSum:
    def test_sum_two_constants(self):
        """Sum signal adds two prior constant signals."""
        registry = {
            "a": build_signal({"Constant": {"value": 3.0}}),
            "b": build_signal({"Constant": {"value": 7.0}}),
        }
        sig = build_signal({"Sum": {"inputs": ["a", "b"]}}, registry)
        assert sig(0.0) == pytest.approx(10.0)

    def test_sum_forward_reference_raises(self):
        """Sum signal raises ValueError for a forward reference."""
        registry: dict = {}
        with pytest.raises(ValueError, match="not found"):
            build_signal({"Sum": {"inputs": ["missing"]}}, registry)


class TestGain:
    def test_gain_scales_signal(self):
        """Gain signal scales the input by k."""
        registry = {"c": build_signal({"Constant": {"value": 4.0}})}
        sig = build_signal({"Gain": {"input": "c", "k": 2.5}}, registry)
        assert sig(0.0) == pytest.approx(10.0)

    def test_gain_forward_reference_raises(self):
        """Gain signal raises ValueError for a forward reference."""
        with pytest.raises(ValueError, match="not found"):
            build_signal({"Gain": {"input": "missing", "k": 1.0}}, {})


class TestIntegrator:
    def test_integrator_initial_value(self):
        """Integrator signal returns x0 at first evaluation."""
        registry = {"c": build_signal({"Constant": {"value": 1.0}})}
        sig = build_signal({"Integrator": {"input": "c", "x0": 5.0}}, registry)
        assert sig(0.0) == pytest.approx(5.0)

    def test_integrator_accumulates(self):
        """Integrator signal accumulates input*dt over time steps."""
        registry = {"c": build_signal({"Constant": {"value": 2.0}})}
        sig = build_signal({"Integrator": {"input": "c", "x0": 0.0}}, registry)
        sig(0.0)  # init
        sig(1.0)  # +2.0*1.0 = 2.0
        result = sig(2.0)  # +2.0*1.0 = 4.0
        assert result == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# build_signal_registry
# ---------------------------------------------------------------------------


class TestBuildSignalRegistry:
    def test_registry_builds_all_signals(self):
        """build_signal_registry creates entries for all declared signals."""
        block = [
            {"id": "pulse", "Gaussian": {"peak": 1.9e-19, "center": 24e-9, "fwhm": 7.06e-9}},
            {"id": "tau", "Constant": {"value": 0.1}},
            {"id": "double", "Sum": {"inputs": ["pulse", "pulse"]}},
        ]
        registry = build_signal_registry(block)
        assert set(registry.keys()) == {"pulse", "tau", "double"}

    def test_registry_preserves_order(self):
        """build_signal_registry preserves declaration order."""
        block = [
            {"id": "a", "Constant": {"value": 1.0}},
            {"id": "b", "Constant": {"value": 2.0}},
        ]
        keys = list(build_signal_registry(block).keys())
        assert keys == ["a", "b"]

    def test_registry_duplicate_id_raises(self):
        """build_signal_registry raises ValueError for duplicate IDs."""
        block = [
            {"id": "dup", "Constant": {"value": 1.0}},
            {"id": "dup", "Constant": {"value": 2.0}},
        ]
        with pytest.raises(ValueError, match="Duplicate signal id"):
            build_signal_registry(block)

    def test_registry_missing_id_raises(self):
        """build_signal_registry raises ValueError if an entry has no id."""
        block = [{"Constant": {"value": 1.0}}]
        with pytest.raises(ValueError, match="must have an 'id' key"):
            build_signal_registry(block)

    def test_registry_combinator_uses_prior_signal(self):
        """build_signal_registry resolves combinators against prior signals."""
        block = [
            {"id": "base", "Constant": {"value": 10.0}},
            {"id": "scaled", "Gain": {"input": "base", "k": 3.0}},
        ]
        reg = build_signal_registry(block)
        assert reg["scaled"](0.0) == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# build_signal error cases
# ---------------------------------------------------------------------------


class TestBuildSignalErrors:
    def test_unknown_kind_raises(self):
        """build_signal raises ValueError for an unknown kind."""
        with pytest.raises(ValueError, match="exactly one source-kind key"):
            build_signal({"id": "x", "UnknownKind": {}})

    def test_no_kind_key_raises(self):
        """build_signal raises ValueError when no kind key is present."""
        with pytest.raises(ValueError, match="exactly one source-kind key"):
            build_signal({"id": "x"})

    def test_combinator_without_registry_raises(self):
        """build_signal raises ValueError for combinator without registry."""
        with pytest.raises(ValueError, match="requires a registry"):
            build_signal({"Sum": {"inputs": ["a", "b"]}})
