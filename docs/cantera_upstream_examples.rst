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

Solver mapping
--------------

Each upstream example uses a specific Cantera integrator strategy.  Boulder
reproduces these by setting ``solver.kind`` in the STONE ``settings:`` block
or in a per-stage ``groups.<id>.solver:`` block.

.. list-table::
   :widths: 35 25 40
   :header-rows: 1

   * - Example
     - ``solver.kind``
     - Notes
   * - ``combustor.py``
     - ``solve_steady``
     - Repeated calls to ``ReactorNet.solve_steady()`` in a
       residence-time continuation sweep (``while combustor.T > 500``).
       The MFC uses a ``closure: residence_time`` so ``mdot`` tracks
       ``reactor.mass / tau``.
   * - ``reactor2.py``
     - ``advance_grid``
     - Explicit time-grid transient via ``network.advance(t)`` for each
       point in a ``grid: {start, stop, dt}`` spec.  A piston ``Wall``
       connects the two reactors; state is sampled at every grid point.
   * - ``nanosecond_pulse_discharge.py``
     - ``micro_step``
     - Chunked micro-steps with ``reinitialize_between_chunks: true``;
       a ``schedule:`` block drives ``reduced_electric_field`` on the
       plasma ``Solution``.  Requires ``clone: false`` on the reactor
       node.

STONE example for ``combustor.py`` round-trip:

The ``combustor.py`` script uses a residence-time closure (``def mdot(t): return reactor.mass / tau``)
and sweeps ``residence_time`` downward while the reactor stays lit.  Boulder's causal layer
represents this with a ``closure: residence_time`` annotation on the MFC and a top-level
``continuation:`` block — both auto-derived by ``sim2stone`` via ``derived_via: ast_match``.

.. code-block:: yaml

   # derived_via: ast_match
   settings:
     solver:
       kind: solve_steady

   # derived_via: ast_match
   continuation:
     parameter: residence_time
     factor: 0.9
     stop_when:
       attribute: T
       less_than: 500.0

   network:
     - id: IdealGasReactor_0
       IdealGasReactor:
         volume: 1.0
         # ...

     - id: MassFlowController_0
       MassFlowController:
         closure: residence_time   # derived_via: ast_match
         tau_s: "{{residence_time}}"
       source: Reservoir_0
       target: IdealGasReactor_0

STONE example for ``reactor2.py`` round-trip:

The ``reactor2.py`` script runs a ``for n in range(300): time += 4e-4; sim.advance(time)`` loop.
Boulder maps this to ``advance_grid`` with a ``grid: {start, stop, dt}`` spec.
No ``signals:`` or ``bindings:`` are needed — this simulation has no time-varying drivers.

.. code-block:: yaml

   # derived_via: ast_match
   settings:
     solver:
       kind: advance_grid
       grid:
         start: 0.0
         stop: 0.12      # 300 steps × 4e-4 s
         dt: 4.0e-4

STONE example for ``nanosecond_pulse_discharge.py`` round-trip:

The ``nanosecond_pulse_discharge.py`` script applies a Gaussian-shaped electric field pulse via
``gaussian_EN = ct.Func1("Gaussian", [peak, center, fwhm])`` and advances in 1 ns micro-steps
with ``sim.reinitialize()`` at each chunk boundary.  Boulder extracts the Gaussian parameters via
AST analysis and emits a causal-layer ``signals:`` + ``bindings:`` block.

.. code-block:: yaml

   # derived_via: ast_match
   settings:
     solver:
       kind: micro_step
       t_total: 90e-9
       chunk_dt: 1e-9
       max_dt: 1e-10
       reinitialize_between_chunks: true

   # derived_via: ast_match
   signals:
     - id: gaussian_EN
       kind: Gaussian
       peak: 1.9e-19    # 190 Td
       center: 24e-9    # pulse centre
       fwhm: 7.06e-9    # full-width at half maximum

   # derived_via: ast_match
   bindings:
     - source: gaussian_EN
       target: nodes.ConstPressureReactor_0.reduced_electric_field

   network:
     - id: ConstPressureReactor_0
       ConstPressureReactor:
         energy: "off"   # PlasmaPhase — cp_mole not implemented
         # clone: false — shares the Solution object with the Reservoir

Bundled scripts
---------------

.. list-table::
   :widths: 28 72
   :header-rows: 1

   * - File
     - Summary
   * - ``cantera_examples/combustor.py``
     - Well-stirred reactor, residence time sweep, ``MassFlowController`` /
       ``PressureController``.  `Original upstream source
       <https://github.com/Cantera/cantera/blob/main/samples/python/reactors/combustor.py>`__.
   * - ``cantera_examples/reactor2.py``
     - Two reactors, piston wall, heat loss (writes ``piston.csv`` in the
       working directory when run).  `Original upstream source
       <https://github.com/Cantera/cantera/blob/main/samples/python/reactors/reactor2.py>`__.
   * - ``cantera_examples/nanosecond_pulse_discharge.py``
     - Nanosecond plasma pulse; uses ``example_data/methane-plasma-pavan-2023.yaml``.
       `Original upstream source
       <https://github.com/Cantera/cantera/blob/main/samples/python/reactors/nanosecond_pulse_discharge.py>`__.

Integration tests under ``tests/test_sim2stone/test_fixture_scripts_sim2stone.py``
execute these scripts via ``sim2stone`` and Boulder headless paths (with
``CANTERA_DATA`` set like CI). To run a script directly with Cantera, use
``python docs/cantera_examples/<name>.py`` from the repo root with
``CANTERA_DATA`` including Cantera's ``data`` and ``data/example_data``
directories.

Additional integration tests in ``tests/test_solver_dispatch.py``,
``tests/test_phase_b_transient.py`` and ``tests/test_phase_c_continuation.py``
validate the solver dispatch, transient grids, micro-step patterns, and
continuation sweeps described in this table.
