# Boulder Configuration Files — STONE v2

This directory contains example configuration files using the **STONE v2** format.
See [STONE_SPECIFICATIONS.md](../STONE_SPECIFICATIONS.md) for the full normative specification and [docs/stone.rst](../docs/stone.rst) for the Sphinx documentation page.

## What is STONE v2?

**STONE** (Standardized Topology Of Network Elements) is Boulder's YAML format for reactor networks.
**v2** (current) uses a `network:` key (single stage) or `stages:` + dynamic stage blocks (multi-stage).
STONE v1 files with top-level `nodes:`/`connections:`/`groups:` are rejected.

## File Structure

### Single-stage (`network:`)

\`yaml
metadata:
title: "My Network"

phases:
gas:
mechanism: gri30.yaml

network:

- id: feed
  Reservoir:
  temperature: 300 K
  composition: N2:0.79,O2:0.21

- id: reactor
  IdealGasReactor:
  volume: 1.0e-3 m\*\*3

- id: feed_to_reactor
  MassFlowController:
  mass_flow_rate: 0.01 kg/s
  source: feed
  target: reactor

settings:
end_time: 1.0
dt: 0.01
\`

### Multi-stage (`stages:` + dynamic blocks)

\`yaml
phases:
gas:
mechanism: gri30.yaml

stages:
stage_a:
solve: advance_to_steady_state
stage_b:
solve: advance
advance_time: 1.0e-3

stage_a:

- id: feed
  Reservoir:
  temperature: 300 K
  composition: CH4:1,O2:2,N2:7.52
- id: psr
  IdealGasConstPressureMoleReactor:
  volume: 1.0e-5 m\*\*3
  initial:
  temperature: 2200 K
  composition: CO2:1,H2O:2,N2:7.52
- id: feed_to_psr
  MassFlowController:
  mass_flow_rate: 1.0e-4 kg/s
  source: feed
  target: psr

stage_b:

- id: pfr_cell_1
  IdealGasConstPressureMoleReactor:
  volume: 2.5e-6 m\*\*3
- id: psr_to_pfr
  source: psr
  target: pfr_cell_1
  mass_flow_rate: 1.0e-4 kg/s
  \`

## Item Schema

Each item in a stage block or `network:` list is a YAML mapping:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier |
| `<KindName>: {...}` | Yes (nodes); No (logical connections) | Kind key with properties |
| `source:` | For connections | Source node id |
| `target:` | For connections | Target node id |

**Nodes** have a kind key without `source`/`target`.
**Connections** have `source` + `target` (and usually a kind key for flow device type).

## Node Kinds

| Kind | Type | Notes |
|------|------|-------|
| `Reservoir` | Boundary | Requires `temperature:` + `composition:` |
| `IdealGasReactor` | Reactor | Use `initial:` for seeding state |
| `IdealGasConstPressureReactor` | Reactor | Const-pressure variant |
| `IdealGasConstPressureMoleReactor` | Reactor | Mole-based const-pressure |
| `OutletSink` | Terminal | Visualization-only sink; cannot be a connection source |

## Connection Kinds

| Kind | Notes |
|------|-------|
| `MassFlowController` | Mass flow device; use `mass_flow_rate:` property |
| `Valve` | Pressure-driven flow; use `valve_coeff:` property |
| `PressureController` | Pressure controller (needs `master:` MFC) |
| `Wall` | Heat coupling between adjacent reactors |
| *(none)* | Logical connection (inter-stage state handoff only) |

## Units

Numeric values may carry explicit units:

`yaml temperature: 300 K        # Kelvin volume: 1.0e-3 m**3       # cubic metres mass_flow_rate: 0.1 kg/s  # kilograms per second pressure: 101325 Pa       # Pascals advance_time: 1.0e-3      # seconds (bare number) `

## Example Files

| File | Description |
|------|-------------|
| `default.yaml` | Single reactor with reservoir inlet |
| `sample_configs2.yaml` | Two-reservoir, two-MFC network |
| `mix_react_streams.yaml` | Mixer with two inlet streams and valve outlet |
| `grouped_nodes.yaml` | Grouped reactors in one stage |
| `staged_psr_pfr.yaml` | Two-stage PSR → PFR chain |

## Cantera Python examples (in `docs/cantera_examples/`)

Vendored Cantera sample scripts used for tests and documentation live under
[`docs/cantera_examples/`](../docs/cantera_examples/). See
[`docs/cantera_upstream_examples.rst`](../docs/cantera_upstream_examples.rst)
for how to run them with Boulder and links to the official Cantera docs.

The directory `configs/cantera_examples/` only keeps a short
[`README.md`](cantera_examples/README.md) pointing to that location.
