"""Deprecated plugin fields stay accepted but warn."""

import sys
import types

import pytest

import boulder.cantera_converter as cc


def test_cyto_element_synthesizers_warns_and_is_ignored(monkeypatch):
    """A plugin that registers `cyto_element_synthesizers` triggers a DeprecationWarning.

    The field stays a plain list so a host that still appends to it keeps importing.
    """
    mod = types.ModuleType("deprecated_field_plugin")
    mod.register_plugins = lambda plugins: plugins.cyto_element_synthesizers.append(
        lambda cfg: []
    )
    monkeypatch.setitem(sys.modules, "deprecated_field_plugin", mod)
    monkeypatch.setenv("BOULDER_PLUGINS", "deprecated_field_plugin")
    monkeypatch.setattr(cc, "_PLUGIN_CACHE", None)

    with pytest.warns(DeprecationWarning, match="cyto_element_synthesizers"):
        plugins = cc.get_plugins()

    assert len(plugins.cyto_element_synthesizers) == 1
