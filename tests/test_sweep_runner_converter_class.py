"""Tests for boulder.sweep_runner's plugins.converter_class support.

A host registers its own DualCanteraConverter subclass (e.g. for a private
mechanism search convention) via ``plugins.converter_class`` so that
out-of-process entry points like the sweep runner resolve mechanism names
the same way the GUI server's own converter does -- previously only
``resolve_mechanism``/``setup`` callbacks passed explicitly by the host
achieved this; converter_class lets the runner derive them automatically.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter
from boulder.sweep_runner import (
    converter_mechanism_resolver,
    prepare_scenario,
    scenario_fingerprint,
)


class _FakeHostConverter(DualCanteraConverter):
    """Stand-in for a host's converter subclass -- never touches Cantera."""

    def __init__(self, mechanism: Optional[str] = None, plugins=None) -> None:
        # Deliberately skip DualCanteraConverter.__init__: it eagerly loads a
        # real ct.Solution, which converter_mechanism_resolver must never
        # trigger just to obtain a method reference.
        raise AssertionError(
            "_FakeHostConverter.__init__ must not be called by "
            "converter_mechanism_resolver -- it should use __new__."
        )

    def resolve_mechanism(self, name: str) -> str:
        return f"/resolved/{name}"


def _config(mechanism: str = "") -> Dict[str, Any]:
    cfg: Dict[str, Any] = {"network": []}
    if mechanism:
        cfg["phases"] = {"gas": {"mechanism": mechanism}}
    return cfg


class TestDefaultResolveMechanism:
    def test_uses_new_not_init(self):
        """Deriving the resolver must not construct a real converter instance."""
        plugins = BoulderPlugins(converter_class=_FakeHostConverter)
        resolve = converter_mechanism_resolver(plugins.converter_class)
        assert resolve("gri30.yaml") == "/resolved/gri30.yaml"

    def test_falls_back_to_base_converter_when_unregistered(self):
        plugins = BoulderPlugins()
        resolve = converter_mechanism_resolver(plugins.converter_class)
        assert resolve("gri30.yaml") == "gri30.yaml"  # passthrough default


class TestScenarioFingerprintUsesConverterClass:
    def test_fingerprint_reflects_host_resolved_mechanism(self, monkeypatch):
        import boulder.sweep_runner as sweep_runner

        plugins = BoulderPlugins(converter_class=_FakeHostConverter)
        monkeypatch.setattr(sweep_runner, "get_plugins", lambda: plugins)

        fp_resolved = scenario_fingerprint(_config("custom_mech.yaml"))
        fp_plain = scenario_fingerprint(
            _config("custom_mech.yaml"), resolve_mechanism=lambda name: name
        )
        # The host's resolver changes the hashed mechanism identity, so the
        # fingerprint must differ from a plain-passthrough resolution.
        assert fp_resolved != fp_plain

    def test_empty_mechanism_resolves_the_default_name(self, monkeypatch):
        """No phases.gas.mechanism declared -- the default name goes to the resolver.

        A single run always solves with a mechanism (the default when none is
        declared), so the key hashes that same default, never an empty name.
        """
        import boulder.sweep_runner as sweep_runner

        seen = []

        class _SpyConverter(DualCanteraConverter):
            def __init__(self, mechanism=None, plugins=None):
                raise AssertionError("must not construct via __init__")

            def resolve_mechanism(self, name: str) -> str:
                seen.append(name)
                return name

        plugins = BoulderPlugins(converter_class=_SpyConverter)
        monkeypatch.setattr(sweep_runner, "get_plugins", lambda: plugins)

        scenario_fingerprint(_config(""))
        assert seen == [sweep_runner.DEFAULT_MECHANISM]


class TestPrepareUsesConverterClass:
    def test_prepare_derives_resolver_when_not_passed(self, monkeypatch):
        import boulder.sweep_runner as sweep_runner

        plugins = BoulderPlugins(converter_class=_FakeHostConverter)
        monkeypatch.setattr(sweep_runner, "get_plugins", lambda: plugins)

        config, mechanism, fingerprint = prepare_scenario(
            _config("custom_mech.yaml"), None
        )
        assert mechanism == "custom_mech.yaml"  # raw name preserved for solve_scenario
        # fingerprint hashed the *resolved* identity -- verify by comparing
        # against an explicit passthrough resolver.
        _, _, fp_plain = prepare_scenario(
            _config("custom_mech.yaml"), lambda name: name
        )
        assert fingerprint != fp_plain
