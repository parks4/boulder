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
