Cantera upstream Python examples
=================================

These scripts are **unchanged Cantera samples** (vendored for Boulder tests and
documentation). They live in ``docs/cantera_examples/`` alongside this page.

Official Cantera documentation
------------------------------

* `Cantera user guide <https://cantera.org/stable/index.html>`__
* `Python samples in the Cantera repository
  <https://github.com/Cantera/cantera/tree/main/samples/python>`__

Running with Boulder
--------------------

From the repository root, with the ``boulder`` conda environment active and
Boulder installed (``pip install -e .``):

.. code-block:: bash

   boulder docs/cantera_examples/combustor.py

This executes the script, converts the resulting reactor network to STONE
YAML, and opens the Boulder UI (or use ``--headless --output-yaml PATH`` for
CLI-only conversion).

For ``sim2stone`` (YAML generation with different options), see ``usage`` and
the Boulder CLI help.

Bundled scripts
---------------

.. list-table::
   :widths: 28 72
   :header-rows: 1

   * - File
     - Summary
   * - ``cantera_examples/combustor.py``
     - Well-stirred reactor, residence time sweep, ``MassFlowController`` /
       ``PressureController``.
   * - ``cantera_examples/reactor2.py``
     - Two reactors, piston wall, heat loss (writes ``piston.csv`` in the
       working directory when run).
   * - ``cantera_examples/nanosecond_pulse_discharge.py``
     - Nanosecond plasma pulse; uses ``example_data/methane-plasma-pavan-2023.yaml``.

Integration tests under ``tests/test_sim2stone/test_fixture_scripts_sim2stone.py``
execute these scripts via ``sim2stone`` and Boulder headless paths (with
``CANTERA_DATA`` set like CI). To run a script directly with Cantera, use
``python docs/cantera_examples/<name>.py`` from the repo root with
``CANTERA_DATA`` including Cantera's ``data`` and ``data/example_data``
directories.
