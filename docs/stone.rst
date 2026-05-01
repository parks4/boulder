STONE Configuration Format
==========================

STONE (Standardized Topology Of Network Elements) is Boulder's YAML-based
configuration format for describing reactor networks.  The current specification
is **STONE v2**.

Overview
--------

A STONE v2 file has two structural variants:

* **Single-stage** (`network:` key) — the entire reactor network lives in a
  flat list of items under `network:`.
* **Multi-stage** (`stages:` key + dynamic stage blocks) — stages are
  declared under `stages:` and each stage's items live in a top-level block
  named after the stage (e.g. `psr_stage:`, `pfr_stage:`).

Both variants share the same item schema: each item is a YAML mapping with an
`id` key and exactly one *kind key* (e.g. `IdealGasReactor:`,
`MassFlowController:`).  Connection items additionally carry `source:` and
`target:` keys.

Dialect Detection
-----------------

Boulder automatically infers the STONE dialect from the top-level keys:

.. code-block:: none

   network:  present               → single-stage v2
   stages:   present               → multi-stage v2
   nodes: / connections: / groups: → STONE v1 (rejected with error)

Normalization
-------------

Boulder converts STONE v2 into an internal format
`{nodes, connections, groups}` via :func:oulder.config.normalize_config.
The normalized representation is then validated by
:func:oulder.validation.validate_normalized_config.

Example: single-stage network
------------------------------

.. code-block:: yaml

   phases:
     gas:
       mechanism: gri30.yaml

   network:
   - id: feed
     Reservoir:
       temperature: 300 K
       composition: CH4:1,O2:2,N2:7.52

   - id: psr
     IdealGasConstPressureMoleReactor:
       volume: 1.0e-5 m**3

   - id: feed_to_psr
     MassFlowController:
       mass_flow_rate: 1.0e-4 kg/s
     source: feed
     target: psr

Example: multi-stage network
-----------------------------

.. code-block:: yaml

   phases:
     gas:
       mechanism: gri30.yaml

   stages:
     psr_stage:
       solve: advance
       advance_time: 1.0e-3
     pfr_stage:
       solve: advance
       advance_time: 1.0e-3

   psr_stage:
   - id: feed
     Reservoir:
       temperature: 300 K
       composition: CH4:1,O2:2,N2:7.52
   - id: psr
     IdealGasConstPressureMoleReactor:
       volume: 1.0e-5 m**3
       initial:
         temperature: 2200 K
         composition: CO2:1,H2O:2,N2:7.52
   - id: feed_to_psr
     MassFlowController:
       mass_flow_rate: 1.0e-4 kg/s
     source: feed
     target: psr

   pfr_stage:
   - id: pfr_cell_1
     IdealGasConstPressureMoleReactor:
       volume: 2.5e-6 m**3
   - id: psr_to_pfr
     source: psr
     target: pfr_cell_1
     mass_flow_rate: 1.0e-4 kg/s

Full specification
------------------

The normative specification is located in `STONE_SPECIFICATIONS.md` at the
repository root.  It covers:

* Allowed top-level keys
* Item schema (nodes vs connections, kind key, property block)
* Node kinds and their physics rules (`Reservoir`, `IdealGasReactor`, etc.)
* Connection kinds (`MassFlowController`, `Valve`, logical connections)
* Initial-condition blocks (`initial:`)
* Unit-bearing literals (e.g. `300 K`, `1.0e-5 m**3`)
* Valid and invalid YAML examples with explanations

See :doc:usage for how to load and run STONE files from Python or the CLI.
