"""
Extending Boulder with a custom reactor plugin.

=====================================================

This example shows how to add a new reactor kind to Boulder using the plugin
API.  A fictional *Monolith* reactor is used — it is simply an
``IdealGasConstPressureMoleReactor`` under the hood, but it demonstrates
every extension point:

- :func:`~boulder.register_reactor_builder` — declarative registration of a
  new reactor kind together with a Pydantic schema for validation.
- ``post_build_hooks`` — a callable run by Boulder after the network is built.
- Subclassing :class:`~boulder.cantera_converter.DualCanteraConverter` to
  override :meth:`~boulder.cantera_converter.DualCanteraConverter.resolve_mechanism`
  and :meth:`~boulder.cantera_converter.DualCanteraConverter.script_load_lines`.
- Subclassing :class:`~boulder.runner.BoulderRunner` to wire the custom
  converter into the full pipeline.

.. tags:: Python, plugins, reactor network, customisation
"""

import cantera as ct
from pydantic import BaseModel, Field

from boulder import register_reactor_builder
from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter
from boulder.config import normalize_config, validate_config
from boulder.runner import BoulderRunner

# %%
# 1. Define the Monolith reactor builder
# ---------------------------------------
# A *reactor builder* is a plain callable with the signature
# ``(converter, node_dict) -> ct.Reactor``.
# Boulder passes the fully-populated node dict from the YAML so the builder
# can read custom properties (``length``, ``cell_density``, etc.).


class MonolithSchema(BaseModel):
    """Pydantic schema for the Monolith reactor kind.

    Registering this schema enables ``boulder validate`` and ``boulder describe``
    to check YAML files and render property panes without running Cantera.
    """

    length: float = Field(1.0, description="[m] Monolith channel length")
    cell_density: float = Field(400.0, description="[1/in²] Channel density (cpsi)")
    temperature: float = Field(300.0, description="[K] Initial temperature")
    pressure: float = Field(101325.0, description="[Pa] Initial pressure")
    composition: str = Field("N2:1", description="Initial gas composition")
    volume: float = Field(1.0e-6, description="[m³] Reactor volume")


def _build_monolith_reactor(converter, node):
    """Build a Monolith reactor from a normalised node dict.

    Falls back to ``IdealGasConstPressureMoleReactor`` so a generic Cantera
    mechanism can be used without any special network class.
    """
    props = node.get("properties", {})
    gas = converter.gas
    T = float(props.get("temperature", 300.0))
    P = float(props.get("pressure", 101325.0))
    X = str(props.get("composition", "N2:1"))
    gas.TPX = T, P, X

    reactor = ct.IdealGasConstPressureMoleReactor(gas)
    volume = float(props.get("volume", 1.0e-6))
    reactor.volume = volume
    return reactor


# %%
# 2. Create a fresh plugin container and register the Monolith builder
# --------------------------------------------------------------------
# In production a plugin package would expose a ``register_plugins(plugins)``
# entry-point callable.  Here we register directly on a
# :class:`~boulder.cantera_converter.BoulderPlugins` instance.

plugins = BoulderPlugins()

register_reactor_builder(
    plugins,
    kind="Monolith",
    builder=_build_monolith_reactor,
    schema=MonolithSchema,
    categories={
        "inputs": {"GEOMETRY": ["length", "cell_density"]},
        "outputs": {"OUTLET": ["T_outlet_K"]},
    },
    default_constraints=[
        {
            "key": "T_outlet_K",
            "description": "Max outlet temperature",
            "operator": "<",
            "threshold": 1800.0,
        }
    ],
)

print(f"Registered reactor kinds: {list(plugins.reactor_builders.keys())}")

# %%
# 3. Attach a post-build hook
# ----------------------------
# Post-build hooks receive the converter and the per-stage config dict after
# each stage has been solved.  They are the right place for logging, KPI
# extraction, or modifying the network before the visualisation step.

build_log: list = []


def _monolith_post_build(converter, cfg):
    n_reactors = len(converter.reactors)
    n_connections = len(converter.connections)
    build_log.append(
        f"post_build: {n_reactors} reactor(s), {n_connections} connection(s)"
    )


plugins.post_build_hooks.append(_monolith_post_build)

# %%
# 4. Subclass DualCanteraConverter
# ---------------------------------
# Overriding :meth:`resolve_mechanism` lets the subclass redirect bare
# mechanism names to a custom data directory.  Overriding
# :meth:`script_load_lines` customises the generated download script so users
# get a ``MonolithRunner.from_yaml(...)`` call rather than a ``BoulderRunner``
# one.


class MonolithConverter(DualCanteraConverter):
    """DualCanteraConverter pre-loaded with the Monolith reactor builder."""

    def resolve_mechanism(self, name: str) -> str:
        """Return *name* unchanged; Cantera handles built-in mechanisms directly."""
        return name

    def script_load_lines(self, config_path: str, plan=None) -> list:
        """Emit a ``MonolithRunner``-based staged-solve block."""
        return self._script_lines_for_runner(
            "from monolith.runner import MonolithRunner",
            "MonolithRunner",
            config_path,
            plan,
        )


# %%
# 5. Subclass BoulderRunner to wire the custom converter in
# ----------------------------------------------------------
# Setting ``converter_class`` is all that is needed.  Every call to
# :meth:`~boulder.runner.BoulderRunner.build` will then instantiate
# ``MonolithConverter`` instead of the base ``DualCanteraConverter``.


class MonolithRunner(BoulderRunner):
    """Orchestrates the full pipeline using ``MonolithConverter``."""

    converter_class = MonolithConverter


# %%
# 6. Build a minimal network and verify the pipeline
# ---------------------------------------------------
# The config below defines a single ``Monolith`` node driven by a reservoir
# at constant mass flow.  After ``runner.build()`` we confirm that the hook
# was called and that the converter is a ``MonolithConverter``.

raw_config = {
    "metadata": {"description": "Monolith plugin example"},
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
            "id": "monolith",
            "type": "Monolith",
            "properties": {
                "temperature": 800,
                "pressure": 101325,
                "composition": "CH4:0.1, N2:0.9",
                "volume": 1.0e-5,
                "length": 0.15,
                "cell_density": 400.0,
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
            "id": "feed_to_monolith",
            "type": "MassFlowController",
            "source": "feed",
            "target": "monolith",
            "properties": {"mass_flow_rate": 1.0e-5},
        },
        {
            "id": "monolith_to_exhaust",
            "type": "PressureController",
            "source": "monolith",
            "target": "exhaust",
            "properties": {"master": "feed_to_monolith", "pressure_coeff": 0.0},
        },
    ],
}

config = validate_config(normalize_config(raw_config))

runner = MonolithRunner(config=config, plugins=plugins)
runner.build()

print(f"Converter type  : {type(runner.converter).__name__}")
print(f"Network type    : {type(runner.network).__name__}")
converter = runner.converter
assert converter is not None
assert isinstance(converter, MonolithConverter)
print(f"Reactors built  : {list(converter.reactors.keys())}")
print(f"Post-build log  : {build_log}")
assert isinstance(runner.network, ct.ReactorNet)
assert len(build_log) >= 1, "Post-build hook must have been called"

print("\nAll assertions passed — Monolith plugin pipeline complete.")
