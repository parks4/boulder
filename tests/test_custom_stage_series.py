"""A CustomStageNetwork's recorded ``.states`` is surfaced as the GUI series.

A plugin stage network that integrates its whole stage internally (its own
macro-grid, a single ``advance`` call) records the real trajectory in
``.states``. The per-step trajectory recorder cannot see such a solve, so
``_series_from_stage_states`` flattens the SolutionArray (plus the network's
scalars) into the ``reactors_series`` shape the plots and panes consume.
"""

import cantera as ct
import numpy as np

from boulder.cantera_converter import _series_from_stage_states


def _states_with_extra() -> ct.SolutionArray:
    gas = ct.Solution("h2o2.yaml")
    arr = ct.SolutionArray(gas, extra=["t", "T_e"])
    for i in range(5):
        gas.TPX = 1000.0 + 100.0 * i, ct.one_atm, "H2:2, O2:1"
        arr.append(  # type: ignore[call-arg]
            gas.state, t=1.0e-9 * i, T_e=2000.0 + 50.0 * i
        )
    return arr


def test_flattens_states_and_extras_and_scalars():
    """t/T/P plus extra columns and scalars all reach the flat series dict."""
    series = _series_from_stage_states(
        _states_with_extra(), scalars={"model_sequence": ["a", "b"], "n": 2}
    )
    assert series is not None
    assert len(series["t"]) == 5
    # Core state variables are always present (``to_pandas`` omits P).
    assert len(series["T"]) == 5 and len(series["P"]) == 5
    # Extra SolutionArray columns are carried through.
    assert series["T_e"][0] == 2000.0 and len(series["T_e"]) == 5
    # Species mole fractions are reshaped to a {species: [...]} mapping.
    assert "H2" in series["X"] and len(series["X"]["H2"]) == 5
    # Mass fractions likewise (regression: only X used to be captured, so the
    # frontend's "Mass fraction" plot silently had nothing to render).
    assert "H2" in series["Y"] and len(series["Y"]["H2"]) == 5
    # Scalars are merged verbatim (panes key off e.g. ``model_sequence``).
    assert series["model_sequence"] == ["a", "b"]
    assert series["n"] == 2


def test_single_point_trajectory_is_rejected():
    """A degenerate (< 2 point) trajectory yields None (keeps the snapshot)."""
    gas = ct.Solution("h2o2.yaml")
    arr = ct.SolutionArray(gas, extra=["t"])
    arr.append(gas.state, t=0.0)
    assert _series_from_stage_states(arr) is None


def test_none_states_is_none():
    """No recorded states -> None (caller falls back to the snapshot)."""
    assert _series_from_stage_states(None) is None


def test_scalars_do_not_override_state_columns():
    """A scalar named like a state column must not clobber the trajectory."""
    series = _series_from_stage_states(_states_with_extra(), scalars={"T": 9999.0})
    assert series is not None
    assert isinstance(series["T"], list) and len(series["T"]) == 5
    assert not np.isclose(series["T"][0], 9999.0)
