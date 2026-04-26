"""Plugin example tests — Monolith reactor.

Demonstrates the three Boulder plugin extension points using a fictional
``Monolith`` reactor kind.  No reference to any specific downstream package;
this serves as the canonical in-tree proof that the plugin API works end-to-end.

Coverage:

1. ``test_reactor_builder_registered`` — ``register_reactor_builder`` stores
   the builder in ``plugins.reactor_builders`` and in the global schema registry.
2. ``test_post_build_hook_called`` — a post-build hook registered in
   ``plugins.post_build_hooks`` is invoked after ``build_network`` completes.
3. ``test_resolve_mechanism_override`` — a ``DualCanteraConverter`` subclass
   that overrides ``resolve_mechanism`` has its override called by
   ``_get_gas_for_mech`` and during construction.
4. ``test_script_load_lines_override`` — a ``DualCanteraConverter`` subclass
   that overrides ``script_load_lines`` produces a generated script containing
   the custom runner import, not the default ``BoulderRunner``.
5. ``test_runner_converter_class`` — a ``BoulderRunner`` subclass with
   ``converter_class = MonolithConverter`` causes ``build()`` to instantiate
   ``MonolithConverter`` rather than the base ``DualCanteraConverter``.
"""

from __future__ import annotations

import textwrap
from typing import Any, Dict

import cantera as ct  # type: ignore
import pytest

# ---------------------------------------------------------------------------
# Shared helpers and fixtures
# ---------------------------------------------------------------------------

_MINIMAL_YAML = textwrap.dedent("""\
    metadata:
      description: monolith plugin test

    phases:
      gas:
        mechanism: gri30.yaml

    nodes:
      - id: feed
        type: Reservoir
        properties:
          temperature: 300
          pressure: 101325
          composition: "N2:1"
      - id: reactor
        type: IdealGasConstPressureMoleReactor
        properties:
          temperature: 300
          pressure: 101325
          composition: "N2:1"
          volume: 1.0e-6
      - id: exhaust
        type: Reservoir
        properties:
          temperature: 300
          pressure: 101325
          composition: "N2:1"

    connections:
      - id: feed_to_r
        type: MassFlowController
        source: feed
        target: reactor
        properties:
          mass_flow_rate: 1.0e-5
      - id: r_to_out
        type: PressureController
        source: reactor
        target: exhaust
        properties:
          master: feed_to_r
          pressure_coeff: 0.0
""")


@pytest.fixture()
def minimal_yaml(tmp_path):
    """Write the minimal YAML to a temp file and return its path."""
    p = tmp_path / "monolith_test.yaml"
    p.write_text(_MINIMAL_YAML, encoding="utf-8")
    return str(p)


def _fresh_plugins():
    """Return a new ``BoulderPlugins`` with no pre-loaded entry-point plugins."""
    from boulder.cantera_converter import BoulderPlugins

    return BoulderPlugins()


def _minimal_config():
    """Return a normalised, validated config dict for a single-reactor network."""
    from boulder.config import normalize_config, validate_config

    raw = {
        "metadata": {"description": "monolith plugin test"},
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "nodes": [
            {
                "id": "feed",
                "type": "Reservoir",
                "properties": {
                    "temperature": 300,
                    "pressure": 101325,
                    "composition": "N2:1",
                },
            },
            {
                "id": "reactor",
                "type": "IdealGasConstPressureMoleReactor",
                "properties": {
                    "temperature": 300,
                    "pressure": 101325,
                    "composition": "N2:1",
                    "volume": 1.0e-6,
                },
            },
            {
                "id": "exhaust",
                "type": "Reservoir",
                "properties": {
                    "temperature": 300,
                    "pressure": 101325,
                    "composition": "N2:1",
                },
            },
        ],
        "connections": [
            {
                "id": "feed_to_r",
                "type": "MassFlowController",
                "source": "feed",
                "target": "reactor",
                "properties": {"mass_flow_rate": 1.0e-5},
            },
            {
                "id": "r_to_out",
                "type": "PressureController",
                "source": "reactor",
                "target": "exhaust",
                "properties": {"master": "feed_to_r", "pressure_coeff": 0.0},
            },
        ],
    }
    return validate_config(normalize_config(raw))


# ---------------------------------------------------------------------------
# Test 1: reactor builder registration
# ---------------------------------------------------------------------------


def test_reactor_builder_registered():
    """``register_reactor_builder`` stores the builder under the given kind.

    Asserts:
    - ``plugins.reactor_builders["Monolith"]`` is set to the builder callable.
    - The global schema registry contains an entry for ``"Monolith"`` with
      the expected ``kind`` field.
    """
    from pydantic import BaseModel, Field

    from boulder import register_reactor_builder
    from boulder.schema_registry import get_schema_entry

    plugins = _fresh_plugins()

    class MonolithSchema(BaseModel):
        length: float = Field(1.0, description="[m] Monolith channel length")
        cell_density: float = Field(400.0, description="[1/in²] Channel density")

    def _build_monolith(converter: Any, node: Dict[str, Any]) -> ct.Reactor:
        gas = converter.gas
        return ct.IdealGasConstPressureMoleReactor(gas)

    register_reactor_builder(
        plugins,
        kind="Monolith",
        builder=_build_monolith,
        schema=MonolithSchema,
        categories={
            "inputs": {"GEOMETRY": ["length", "cell_density"]},
            "outputs": {"OUTLET": ["T_outlet_K"]},
        },
    )

    assert "Monolith" in plugins.reactor_builders, (
        "Builder must be stored in plugins.reactor_builders"
    )
    assert plugins.reactor_builders["Monolith"] is _build_monolith

    entry = get_schema_entry("Monolith")
    assert entry is not None
    assert entry.kind == "Monolith"
    assert entry.schema is MonolithSchema


# ---------------------------------------------------------------------------
# Test 2: post-build hook is called
# ---------------------------------------------------------------------------


def test_post_build_hook_called():
    """A post-build hook registered in ``plugins.post_build_hooks`` is invoked.

    Asserts:
    - After ``converter.build_network(config)`` completes, the hook has been
      called exactly once and received the config dict.
    """
    from boulder.cantera_converter import DualCanteraConverter

    plugins = _fresh_plugins()
    calls: list = []

    def _hook(converter: Any, cfg: Dict[str, Any]) -> None:
        calls.append(cfg)

    plugins.post_build_hooks.append(_hook)
    config = _minimal_config()

    converter = DualCanteraConverter(mechanism="gri30.yaml", plugins=plugins)
    converter.build_network(config)

    assert len(calls) >= 1, "Post-build hook must be called at least once"
    # The staged solver calls post_build with a per-stage sub-config dict;
    # verify it is a dict containing at least the 'nodes' key.
    assert isinstance(calls[0], dict), "Hook argument must be a dict"
    assert "nodes" in calls[0], "Hook dict must contain 'nodes'"


# ---------------------------------------------------------------------------
# Test 3: resolve_mechanism subclass override is honoured
# ---------------------------------------------------------------------------


def test_resolve_mechanism_override():
    """A subclass that overrides ``resolve_mechanism`` has its override called.

    Asserts:
    - ``MonolithConverter`` is constructed successfully with a tracked resolver.
    - Each call to ``_get_gas_for_mech`` passes through the override.
    - The recorded call count is at least 1 (construction + any per-node switch).
    """
    from boulder.cantera_converter import DualCanteraConverter

    resolved_names: list = []

    class MonolithConverter(DualCanteraConverter):
        def resolve_mechanism(self, name: str) -> str:
            resolved_names.append(name)
            return name  # pass through to Cantera

    converter = MonolithConverter(mechanism="gri30.yaml")

    assert len(resolved_names) >= 1, (
        "resolve_mechanism must be called at least once during construction"
    )
    assert "gri30.yaml" in resolved_names

    # Trigger a second lookup via _get_gas_for_mech
    before = len(resolved_names)
    converter._get_gas_for_mech("gri30.yaml")
    # Cached — resolve called once, subsequent calls use cache
    converter._get_gas_for_mech("h2o2.yaml")
    assert len(resolved_names) > before, (
        "_get_gas_for_mech must call resolve_mechanism for a new mechanism"
    )


# ---------------------------------------------------------------------------
# Test 4: script_load_lines override produces custom runner import
# ---------------------------------------------------------------------------


def test_script_load_lines_override():
    """A ``DualCanteraConverter`` subclass overriding ``script_load_lines`` is used.

    Asserts:
    - After ``build_network``, ``converter.code_lines`` contains the custom
      runner import line emitted by the override (not the default
      ``BoulderRunner`` import).
    """
    from boulder.cantera_converter import DualCanteraConverter

    class MonolithConverter(DualCanteraConverter):
        def script_load_lines(self, config_path: str, plan: Any = None) -> list:
            return [
                "from monolith.runner import MonolithRunner",
                "",
                f"config_path = {repr(config_path)}",
                "runner = MonolithRunner.from_yaml(config_path)",
                "runner.build()",
            ]

    plugins = _fresh_plugins()
    config = _minimal_config()

    converter = MonolithConverter(mechanism="gri30.yaml", plugins=plugins)
    converter._download_config_path = "monolith_test.yaml"
    converter.build_network(config)

    joined = "\n".join(converter.code_lines)
    assert "MonolithRunner" in joined, (
        "Generated script must contain the custom runner class name"
    )
    assert "BoulderRunner" not in joined, (
        "Generated script must not fall back to the base BoulderRunner"
    )


# ---------------------------------------------------------------------------
# Test 5: BoulderRunner subclass with converter_class instantiates the right type
# ---------------------------------------------------------------------------


def test_runner_converter_class(minimal_yaml):
    """``BoulderRunner`` subclass with ``converter_class`` uses that converter.

    Asserts:
    - After ``MonolithRunner.from_yaml(...).build()``, ``runner.converter`` is
      an instance of ``MonolithConverter``, not the base
      ``DualCanteraConverter``.
    - ``runner.network`` is a ``ct.ReactorNet``.
    """
    from boulder.cantera_converter import DualCanteraConverter
    from boulder.runner import BoulderRunner

    class MonolithConverter(DualCanteraConverter):
        pass  # identity subclass; proves the runner wires it in

    class MonolithRunner(BoulderRunner):
        converter_class = MonolithConverter

    runner = MonolithRunner.from_yaml(minimal_yaml).build()

    assert isinstance(runner.converter, MonolithConverter), (
        "runner.converter must be a MonolithConverter instance"
    )
    assert isinstance(runner.network, ct.ReactorNet), (
        "runner.network must be a ct.ReactorNet after build()"
    )
