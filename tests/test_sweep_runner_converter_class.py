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
    _default_resolve_mechanism,
    _prepare,
    scenario_fingerprint,
)


class _FakeHostConverter(DualCanteraConverter):
    """Stand-in for a host's converter subclass -- never touches Cantera."""

    def __init__(self, mechanism: Optional[str] = None, plugins=None) -> None:
        # Deliberately skip DualCanteraConverter.__init__: it eagerly loads a
        # real ct.Solution, which _default_resolve_mechanism must never
        # trigger just to obtain a method reference.
        raise AssertionError(
            "_FakeHostConverter.__init__ must not be called by "
            "_default_resolve_mechanism -- it should use __new__."
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
        resolve = _default_resolve_mechanism(plugins)
        assert resolve("gri30.yaml") == "/resolved/gri30.yaml"

    def test_falls_back_to_base_converter_when_unregistered(self):
        plugins = BoulderPlugins()
        resolve = _default_resolve_mechanism(plugins)
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

    def test_empty_mechanism_never_calls_resolver(self, monkeypatch):
        """No phases.gas.mechanism declared -- must not invoke the resolver at all.

        A host's resolve_mechanism may not handle an empty/missing mechanism
        name sensibly (e.g. it might resolve "" to a directory instead of
        raising) -- scenario_fingerprint must not call it in that case.
        """
        import boulder.sweep_runner as sweep_runner

        def _boom(name: str) -> str:
            raise AssertionError("resolver must not be called for an empty mechanism")

        class _BoomConverter(DualCanteraConverter):
            def __init__(self, mechanism=None, plugins=None):
                raise AssertionError("must not construct via __init__")

            def resolve_mechanism(self, name: str) -> str:
                return _boom(name)

        plugins = BoulderPlugins(converter_class=_BoomConverter)
        monkeypatch.setattr(sweep_runner, "get_plugins", lambda: plugins)

        # Must not raise.
        scenario_fingerprint(_config(""))


class TestPrepareUsesConverterClass:
    def test_prepare_derives_resolver_when_not_passed(self, monkeypatch):
        import boulder.sweep_runner as sweep_runner

        plugins = BoulderPlugins(converter_class=_FakeHostConverter)
        monkeypatch.setattr(sweep_runner, "get_plugins", lambda: plugins)

        config, mechanism, fingerprint = _prepare(_config("custom_mech.yaml"), None)
        assert mechanism == "custom_mech.yaml"  # raw name preserved for _solve
        # fingerprint hashed the *resolved* identity -- verify by comparing
        # against an explicit passthrough resolver.
        _, _, fp_plain = _prepare(_config("custom_mech.yaml"), lambda name: name)
        assert fingerprint != fp_plain
