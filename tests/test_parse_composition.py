"""Regression test: composition strings with comma-bearing species names.

Some real Cantera mechanisms (e.g. ``n-heptane-NUIG-2016.yaml``, the
n-heptane oxidation mechanism from Zhang et al. 2016) include species names
that themselves contain a literal comma, such as ``C6H101-3,3`` or
``C8H141-5,3``. Cantera's own composition-string parser (``Phase.X = "..."``)
handles this correctly. ``DualCanteraConverter.parse_composition`` previously
did not: it split on every ``,`` first and then every ``:``, which silently
misparsed any composition string containing such a species and raised
``ValueError: not enough values to unpack``.
"""

from __future__ import annotations

import pytest

from boulder.cantera_converter import DualCanteraConverter


@pytest.fixture()
def converter() -> DualCanteraConverter:
    return DualCanteraConverter(mechanism="gri30.yaml")


def test_parse_composition_simple(converter: DualCanteraConverter) -> None:
    assert converter.parse_composition("H2:0.667, O2:0.333") == {
        "H2": pytest.approx(0.667),
        "O2": pytest.approx(0.333),
    }


def test_parse_composition_species_name_with_comma(
    converter: DualCanteraConverter,
) -> None:
    """A species name containing ',' must not be split as an entry separator."""
    parsed = converter.parse_composition("C6H101-3,3:5.27465e-08,O2:0.0275,HE:0.9675")
    assert parsed == {
        "C6H101-3,3": pytest.approx(5.27465e-08),
        "O2": pytest.approx(0.0275),
        "HE": pytest.approx(0.9675),
    }


def test_parse_composition_multiple_comma_species(
    converter: DualCanteraConverter,
) -> None:
    """Several comma-bearing species names in the same string, back to back."""
    parsed = converter.parse_composition(
        "C8H141-5,3:1e-06,C8H131-5,3,SA:2e-07,NC7H16:0.005"
    )
    assert parsed == {
        "C8H141-5,3": pytest.approx(1e-06),
        "C8H131-5,3,SA": pytest.approx(2e-07),
        "NC7H16": pytest.approx(0.005),
    }
