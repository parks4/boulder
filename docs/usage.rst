Usage
=====

From Python
-----------

Run Boulder programmatically (as in ``run.py``)::

    import uvicorn
    if __name__ == "__main__":
        uvicorn.run("boulder.api.main:app", host="0.0.0.0", port=8050, reload=True)

From the CLI
------------

After installation, use the ``boulder`` command::

    boulder                 # launches the server & opens the interface
    boulder some_file.yaml  # launches the server preloading a YAML config

Optional flags::

    boulder --host 0.0.0.0 --port 8050 --debug
    boulder some_file.yaml --no-open

Running scenario sweeps
------------------------

A STONE config may declare extra cases inline via a top-level ``scenarios:``
block (a mapping of ``id -> overlay``) and/or a ``sweep:``/``sweeps:`` block
(a Cartesian-product parameter sweep). See ``STONE_SPECIFICATIONS.md``
(Section 14) for the full schema. Whenever ``scenarios:`` is declared,
Boulder always adds an unmodified copy of the base config as its own
``BASELINE`` entry, first in the run set.

**From the GUI**

The sidebar's "Run Simulation" button is a **split button**: a small
caret/chevron sits to its right (accessible name "Choose run action").
Clicking it opens a menu with:

.. list-table::
   :header-rows: 1

   * - Option
     - Description
   * - Run Simulation
     - Solve the single reactor as configured.
   * - Force Run
     - Solve ignoring cache.
   * - Run Sweep
     - Run *N* scenarios (the count is read live from the config).
   * - Add Scenario…
     - Create a new scenario overlay and edit its YAML.

Selecting "Run Sweep" switches the split button's primary action to "Run
Sweep (N scenarios)" — you then click the (now relabeled) primary button to
actually start it. Passing ``--sweep`` on the command line (see below) skips
this: the run-set starts automatically as soon as the page loads.

The right-hand **Scenario Pane** lists every declared scenario (id, plus
"Edit scenario YAML" / "Delete scenario" actions per entry) and an "Add
Scenario" button to create new ones — before a sweep has run, it reads
"Not computed yet — Run Sweep to solve them."

.. note::

   Screenshot placeholder — the sidebar with the "Run Simulation" split
   button and its caret menu expanded (showing Run Simulation / Force Run /
   Run Sweep / Add Scenario…), plus the Scenario Pane listing BASELINE and
   the declared scenario ids.

**From the CLI**

::

    boulder some_file.yaml --sweep              # GUI, run-set auto-started on load
    boulder some_file.yaml --sweep --headless    # no GUI: run every scenario, print
                                                  # "scenario N/M" progress, and write
                                                  # <config-stem>_scenarios.h5

**Both flags are required for a true headless run.** ``--sweep`` alone still
starts a web server (with the run-set auto-started instead of requiring a
click); ``--headless`` is what skips the server entirely and runs everything
in the terminal. This is implemented by a host-registered
``BoulderPlugins.sweep_runner`` (see :func:`boulder.sweep_runner.run`); a
plain ``boulder`` install without a host plugin falls back to
:class:`~boulder.cantera_converter.DualCanteraConverter` directly.

Environment variables
---------------------

You can set ``BOULDER_CONFIG_PATH`` (or ``BOULDER_CONFIG``) to preload a YAML file::

    BOULDER_CONFIG_PATH=path/to/config.yaml boulder

Extending Boulder with plugins
------------------------------

Boulder's plugin system lets downstream packages add custom reactor kinds,
post-build hooks, mechanism resolvers, and UI panes without modifying
the core library.

**What counts as a plugin**

A plugin is a Python module that exposes a registrar function::

    def register_plugins(plugins):
        ...

The registrar receives the shared ``BoulderPlugins`` container and registers
one or more extension points on it.

**Quick summary of extension points**

- ``plugins.reactor_builders[kind] = fn`` — register a callable
  ``(converter, node_dict) -> ct.Reactor`` for a new YAML ``type`` key.
- :func:`boulder.register_reactor_builder` — same as above, plus a Pydantic
  schema so ``boulder validate`` and ``boulder describe`` can inspect the kind.
- ``plugins.post_build_hooks`` — list of ``(converter, cfg) -> None``
  callables invoked after each staged-solve stage.
- Subclass :class:`~boulder.cantera_converter.DualCanteraConverter` and
  override :meth:`~boulder.cantera_converter.DualCanteraConverter.resolve_mechanism`
  to redirect bare mechanism names to a custom data directory.
- Subclass :class:`~boulder.runner.BoulderRunner` and set
  ``converter_class`` to wire the custom converter into the full pipeline.

**Plugin discovery**

Boulder discovers plugins automatically at startup via two mechanisms:

1. *Entry points* (``boulder.plugins`` group) — the canonical path for packaged
   plugins distributed via ``pip``.  Declare in your ``pyproject.toml``::

       [project.entry-points."boulder.plugins"]
       my_plugin = "my_package.boulder_plugins:register_plugins"

2. *Environment variable* (``BOULDER_PLUGINS``) — comma- or semicolon-separated
   module names
   for local or unpackaged plugins::

       BOULDER_PLUGINS=my_local_pkg.boulder_plugins boulder

   Module names are imported with ``importlib.import_module(...)``, so
   resolution follows normal Python ``sys.path`` rules from your active
   environment.

Inspect which plugins loaded with::

    boulder plugins list

**Working example**

See :doc:`auto_examples/plugin_example` for a complete, runnable demonstration
using a ``Monolith`` reactor that exercises all extension points above.

Full architecture and plugin reference: ``ARCHITECTURE.md`` at the repository
root (plugin system, staged networks, definition, and discovery).
