"""Reactor reports carry the reactor's own design warnings (duck-typed)."""

from types import SimpleNamespace

import numpy as np

from boulder.simulation_worker import design_warnings_of, generate_reactor_reports


def _phase():
    return SimpleNamespace(
        T=1200.0,
        P=101325.0,
        X=np.array([0.5, 0.5]),
        Y=np.array([0.4, 0.6]),
        species_names=["A", "B"],
        molecular_weights=np.array([2.0, 28.0]),
        report=lambda: "thermo",
    )


def _results(rid):
    return {
        "reactors": {
            rid: {
                "T": [300.0, 1200.0],
                "P": [101325.0, 101325.0],
                "X": {"A": [1.0, 0.5], "B": [0.0, 0.5]},
            }
        }
    }


def test_a_reactor_without_the_method_reports_no_warnings():
    """Assert plain reactors get an empty ``warnings`` list, not a missing key."""
    reactor = SimpleNamespace(phase=_phase(), volume=1.0)
    converter = SimpleNamespace(reactors={"r": reactor})
    reports = generate_reactor_reports(converter, _results("r"))
    assert reports["r"]["warnings"] == []


def test_the_reactors_design_warnings_are_carried_verbatim():
    """Assert ``design_warnings()`` lines land in the report as strings."""
    lines = [
        "Inlet temperature above the rating -- T_in = 1823 violates T_in <= 873.15"
    ]
    reactor = SimpleNamespace(phase=_phase(), volume=1.0, design_warnings=lambda: lines)
    converter = SimpleNamespace(reactors={"r": reactor})
    reports = generate_reactor_reports(converter, _results("r"))
    assert reports["r"]["warnings"] == lines


def test_a_failing_design_warnings_method_does_not_sink_the_report():
    """Assert an exception inside the host method yields ``[]`` and keeps the report."""

    def boom():
        raise RuntimeError("not solved yet")

    reactor = SimpleNamespace(phase=_phase(), volume=1.0, design_warnings=boom)
    assert design_warnings_of(reactor) == []
    converter = SimpleNamespace(reactors={"r": reactor})
    reports = generate_reactor_reports(converter, _results("r"))
    assert reports["r"]["thermo_report"] == "thermo"
    assert reports["r"]["warnings"] == []
