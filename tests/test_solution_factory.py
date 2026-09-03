"""Tests for the parse-once Solution factory behind the converter.

A large mechanism makes ``ct.Solution(file)`` cost seconds, so the converter
parses each file once per process and derives every other object it needs
from the parsed parts (``ctutils.load_solution`` / ``derive_solution``, exposed
through the overridable ``DualCanteraConverter.create_solution`` hook).
"""

from __future__ import annotations

import copy

import cantera as ct
import numpy as np

from boulder import ctutils
from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config
from boulder.staged_solver import build_stage_graph, solve_staged

MECH = "gri30.yaml"

_TWO_STAGE = {
    "groups": {
        "stage_a": {
            "mechanism": MECH,
            "solver": {"kind": "advance", "advance_time": 1e-6},
        },
        "stage_b": {
            "mechanism": MECH,
            "solver": {"kind": "advance", "advance_time": 1e-6},
        },
    },
    "phases": {"gas": {"mechanism": MECH}},
    "nodes": [
        {
            "id": "feed",
            "type": "Reservoir",
            "properties": {
                "group": "stage_a",
                "temperature": 1200.0,
                "pressure": 101325.0,
                "composition": "N2:1",
            },
        },
        {
            "id": "reactor",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_a",
                "temperature": 1200.0,
                "pressure": 101325.0,
                "composition": "N2:1",
                "volume": 1e-5,
            },
        },
        {
            "id": "downstream",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "group": "stage_b",
                "temperature": 900.0,
                "pressure": 101325.0,
                "composition": "N2:1",
                "volume": 5e-6,
            },
        },
        {
            "id": "sink",
            "type": "Reservoir",
            "properties": {
                "group": "stage_b",
                "temperature": 900.0,
                "pressure": 101325.0,
                "composition": "N2:1",
            },
        },
    ],
    "connections": [
        {
            "id": "feed_to_reactor",
            "type": "MassFlowController",
            "source": "feed",
            "target": "reactor",
            "properties": {"mass_flow_rate": 1e-4},
            "group": "stage_a",
        },
        {
            "id": "a_to_b",
            "type": "MassFlowController",
            "source": "reactor",
            "target": "downstream",
            "properties": {"mass_flow_rate": 1e-4},
        },
        {
            "id": "b_to_sink",
            "type": "MassFlowController",
            "source": "downstream",
            "target": "sink",
            "properties": {"mass_flow_rate": 1e-4},
            "group": "stage_b",
        },
    ],
}


def test_derived_solution_matches_the_parsed_one_and_is_independent():
    base = ctutils.load_solution(MECH)
    full = ctutils.derive_solution(base, kinetics=True)
    lite = ctutils.derive_solution(base, kinetics=False)

    assert full.n_reactions == base.n_reactions
    assert lite.n_reactions == 0
    assert full.species_names == base.species_names == lite.species_names
    assert full.transport_model == "none"
    assert full.mechanism_path == lite.mechanism_path == base.source

    state = 1500.0, ct.one_atm, "CH4:1, O2:2, N2:7.52"
    base.TPX = state
    full.TPX = state
    np.testing.assert_array_equal(full.net_production_rates, base.net_production_rates)
    assert full.enthalpy_mass == base.enthalpy_mass

    lite.TPX = 300.0, ct.one_atm, "H2:1"
    assert full.T == 1500.0  # independent state
    assert base.T == 1500.0


def test_derived_phase_mixes_with_a_file_loaded_one():
    """``Quantity`` keys compatibility on the phase name, which is carried over."""
    from_file = ct.Solution(MECH)
    derived = ctutils.derive_solution(ctutils.load_solution(MECH), kinetics=False)
    from_file.TPX = 1500.0, ct.one_atm, "CH4:1"
    derived.TPX = 300.0, ct.one_atm, "H2:1"
    mixed = ct.Quantity(from_file, mass=1, constant="HP") + ct.Quantity(
        derived, mass=1, constant="HP"
    )
    assert 300.0 < mixed.T < 1500.0


def test_converter_parses_the_mechanism_file_once_per_process():
    ctutils._PARSED_SOLUTIONS.clear()
    n_before = len(ctutils._PARSED_SOLUTIONS)

    for _ in range(2):
        conv = DualCanteraConverter(mechanism=MECH)
        cfg = normalize_config(copy.deepcopy(_TWO_STAGE))
        solve_staged(conv, build_stage_graph(cfg), cfg)

    assert len(ctutils._PARSED_SOLUTIONS) == n_before + 1
    template = ctutils._PARSED_SOLUTIONS[MECH]
    # Converter gases are derived from the template, never the template itself.
    assert conv.gas is not template
    # The engine never reads transport properties: no fit on the shared gas.
    assert conv.gas.transport_model == "none"
    for reactor in conv.reactors.values():
        assert reactor.phase is not template


def test_reservoir_and_reactor_contents_are_independent_of_the_shared_gas():
    conv = DualCanteraConverter(mechanism=MECH)
    cfg = normalize_config(copy.deepcopy(_TWO_STAGE))
    solve_staged(conv, build_stage_graph(cfg), cfg)

    feed = conv.reactors["feed"]
    reactor = conv.reactors["reactor"]
    assert feed.phase is not conv.gas
    assert reactor.phase is not conv.gas
    assert feed.phase is not reactor.phase
    # A Reservoir holds a boundary state and never integrates chemistry.
    assert feed.phase.n_reactions == 0
    assert reactor.phase.n_reactions == conv.gas.n_reactions

    T_feed = feed.phase.T
    conv.gas.TPX = 400.0, ct.one_atm, "H2:1"
    assert feed.phase.T == T_feed
    assert reactor.phase.T != 400.0


def test_a_subclass_can_serve_solutions_from_its_own_cache():
    served: list[tuple[str, bool, bool]] = []

    class Host(DualCanteraConverter):
        def create_solution(self, mech_name, *, kinetics=True, transport=False):
            served.append((mech_name, kinetics, transport))
            return super().create_solution(
                mech_name, kinetics=kinetics, transport=transport
            )

    conv = Host(mechanism=MECH)
    cfg = normalize_config(copy.deepcopy(_TWO_STAGE))
    solve_staged(conv, build_stage_graph(cfg), cfg)

    assert any(k for _, k, _ in served)  # the converter's shared gas / reactors
    assert any(not k for _, k, _ in served)  # templates / carriers
    assert not any(t for _, _, t in served)  # nothing asks for a transport fit
    assert all(m.endswith(MECH) for m, _, _ in served)  # resolved path or bare name
