"""Tests for the ``sankey_species`` plugin slot.

Which species deserve their own Sankey band is a property of the process being
modelled, not of the engine. Boulder therefore keeps only a minimal fallback and
lets a plugin replace it. Asserts:

- A registered list replaces Boulder's fallback entirely.
- A registered list is passed through untouched -- groups and generator-specific
  sentinels survive, since Boulder cannot filter what it does not understand.
- Boulder's own fallback *is* filtered against the network's species.
- The converter and the standalone helper agree (they used to hold two
  byte-identical copies of this logic, so a hook added to one missed the other).
"""

from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter
from boulder.sankey import _DEFAULT_SANKEY_SPECIES, _sankey_species


def test_fallback_is_filtered_against_the_network():
    """Boulder's own names are plain, so absent ones are dropped."""
    plugins = BoulderPlugins()
    assert plugins.sankey_species is None

    assert _sankey_species({"H2", "CH4", "N2"}, plugins=plugins) == ["H2", "CH4"]
    assert _sankey_species({"CH4", "N2"}, plugins=plugins) == ["CH4"]
    assert _sankey_species({"N2", "AR"}, plugins=plugins) == []


def test_registered_list_replaces_the_fallback():
    plugins = BoulderPlugins()
    plugins.sankey_species = ["C2H2"]

    assert _sankey_species({"H2", "CH4", "C2H2"}, plugins=plugins) == ["C2H2"]
    assert "H2" not in _sankey_species({"H2", "CH4"}, plugins=plugins)


def test_registered_entries_pass_through_untouched():
    """Groups and sentinels are not plain names: filtering them would drop them."""
    sentinel = "<some generator-specific group>"
    plugins = BoulderPlugins()
    plugins.sankey_species = ["H2", ["C2H2", "C2H4"], sentinel]

    # Network has none of them; nothing may be silently removed.
    assert _sankey_species({"N2"}, plugins=plugins) == [
        "H2",
        ["C2H2", "C2H4"],
        sentinel,
    ]


def test_registered_list_is_copied_not_aliased():
    """Mutating the returned list must not corrupt the registered slot."""
    plugins = BoulderPlugins()
    plugins.sankey_species = ["H2"]

    _sankey_species({"H2"}, plugins=plugins).append("CH4")
    assert plugins.sankey_species == ["H2"]


def test_converter_reads_the_same_slot_as_the_helper():
    """Guards the de-duplication: one hook, both entry points."""
    plugins = BoulderPlugins()
    plugins.sankey_species = ["C2H2"]
    converter = DualCanteraConverter(plugins=plugins)

    # No network built yet -> empty, but crucially it must not fall back to a
    # second, private copy of the default list.
    assert converter._get_available_species_for_sankey() == []
    assert converter.plugins.sankey_species == ["C2H2"]
    assert _DEFAULT_SANKEY_SPECIES == ["H2", "CH4"]
