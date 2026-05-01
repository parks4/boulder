# STONE v2 Specification

**STONE** — Structured Type-Oriented Network Expressions — is the YAML dialect Boulder uses to
describe Cantera reactor networks. This document is the normative contract for **STONE v2**, the
current authored format.

For a quick introduction and worked examples, see `docs/stone.rst` (online) or `configs/README.md`.

---

## 1. Dialect Detection

STONE v2 files carry no explicit version header. Boulder infers the dialect from the top-level
shape:

| Shape | Dialect |
|---|---|
| Top-level `network:` list | STONE v2 — single stage |
| Top-level `stages:` mapping | STONE v2 — staged |
| Top-level `nodes:`, `connections:`, or `groups:` | STONE v1 — **rejected** |
| None of the above | Invalid — error |

Files that mix `stages:` and `network:` at the same level are rejected.

---

## 2. Allowed Top-Level Keys

```
metadata   phases   settings   stages   network   export   sweeps   scenarios
```

Dynamic stage block names (declared under `stages:`) are also allowed at the top level.

**Reserved names that cannot be used as stage ids:** `metadata`, `phases`, `settings`, `stages`,
`network`, `nodes`, `connections`.

---

## 3. Common Sections

### `metadata:`

A mapping for documentation and provenance fields. Key fields: `title`, `description`,
`scenario_id`, `author`, `date`, `project`. See `boulder/validation.py:MetadataModel` for the
full vocabulary.

### `phases:`

Mechanism registry. Maps phase aliases to Cantera mechanism files:

```yaml
phases:
  gas:
    mechanism: gri30.yaml
  fuel:
    mechanism: Fincke_GRC.yaml
```

A `mechanism:` value in a stage or node may be a phase alias (`gas`, `fuel`) or a raw mechanism
filename (`gri30.yaml`). Resolution order: **node** > **stage** > `phases.gas.mechanism` >
Boulder default.

### `settings:`

Simulation-level settings passed to the solver and post-processing. Schema is open; see individual
plugin documentation for recognized keys.

### `export:`

KPI functions, figure generators, calc-note targets. Consumed by `bloc.yaml_utils` and
`bloc.calc_note`. Not interpreted by Boulder core.

---

## 4. Staged Networks — `stages:`

Use `stages:` when the reactor network is solved in sequential steps (e.g. torch → PSR → PFR).

### Stage metadata

```yaml
stages:
  torch_stage:
    mechanism: gri30.yaml       # required
    solve: advance              # required: "advance" or "advance_to_steady_state"
    advance_time: 1.0e-3        # required iff solve == advance; forbidden otherwise
```

### Stage content blocks

Each key under `stages:` must have a matching top-level block of the same name, and vice versa.
The block is a YAML list of items (nodes and connections):

```yaml
torch_stage:
- id: upstream
  Reservoir:
    temperature: 300 K
    composition: CH4:1

- id: torch
  DesignTorchInstantaneousHeating:
    pressure: 1.3 bar
    t_res_s: 1 ms
    electric_power_kW: 111.0
    torch_eff: 0.80
    gen_eff: 0.80

- id: upstream_to_torch
  MassFlowController:
    mass_flow_rate: 470 kg/d
  source: upstream
  target: torch
```

### Stage execution order

Stages are executed in topological order over inter-stage edges. The mapping order in `stages:` is
a readability hint only. Cycles in the stage dependency graph fail validation.

### Inter-stage edge ownership

Inter-stage edges are declared in the **downstream** stage block. The downstream stage is the one
whose reactor is initialized from the upstream outlet state.

---

## 5. Single-Stage Networks — `network:`

Omit `stages:` and use the reserved `network:` key for simple, single-stage simulations:

```yaml
network:
- id: inlet
  Reservoir:
    temperature: 300 K
    pressure: 1 atm
    composition: O2:1, N2:3.76

- id: reactor
  IdealGasReactor:
    volume: 1 L

- id: inlet_to_reactor
  MassFlowController:
    mass_flow_rate: 0.1 kg/s
  source: inlet
  target: reactor
```

`network:` is sugar for a single stage named `default`. It is mutually exclusive with `stages:`.

---

## 6. Item Schema

Each item in a stage block or `network:` list must have a unique `id:` and exactly one of the
following shapes.

### Node

A node item has exactly one **node kind key** (`Reservoir`, `IdealGasReactor`,
`DesignTorchInstantaneousHeating`, etc.) and no `source:` or `target:`.

```yaml
- id: my_reactor
  IdealGasReactor:
    volume: 1 L
```

### Connection

A connection item has both `source:` and `target:`. It may have one **flow-device kind key**
(`MassFlowController`, `Valve`, `PressureController`, `Wall`). If it has no kind key, it is a
**logical staged connection** (see Section 8).

```yaml
- id: inlet_mfc
  MassFlowController:
    mass_flow_rate: 0.1 kg/s
  source: inlet
  target: reactor
```

### Validation rules

- `source:` alone (no `target:`) → invalid.
- `target:` alone (no `source:`) → invalid.
- Both `source:` and `target:` on a node item → invalid.
- Unknown keys on an item fail validation (catches typos such as `sources:`).
- Node `id:` values are globally unique across all stage blocks.
- `source:` and `target:` resolve globally by id, regardless of which stage block declared the node.

### `initial:` block

A reactor may declare an `initial:` sub-block to seed integration when needed:

```yaml
- id: batch
  IdealGasReactor:
    volume: 1 L
    initial:
      temperature: 1000 K
      pressure: 1 atm
      composition: CH4:1, O2:2, N2:7.52
```

`initial:` is a guess or seed, never a constraint. If omitted, Boulder seeds the reactor from the
upstream state source. A reactor with no upstream state source must declare `initial:`.

---

## 7. Node Kinds

Kind-specific fields are defined by each reactor-kind schema registered in Boulder's plugin
registry. STONE v2 specifies the outer grammar; the kind registry specifies the inner grammar.

### Reactor state placement

| Kind | `pressure:` | `temperature:` |
|---|---|---|
| Const-volume (`IdealGasReactor`, etc.) | under `initial:` | under `initial:` |
| Const-pressure (`IdealGasConstPressureReactor`, `DesignPSR`) | top-level operating constraint | invalid unless kind defines isothermal mode |
| PFR-like (`DesignPFR`, `DesignPFRThinShell`) | top-level operating set-point | invalid unless kind defines isothermal mode |

Top-level reactor `temperature:` is invalid unless the kind schema explicitly defines a
fixed-temperature model option.

### Sizing

Each reactor kind defines one sizing basis. Authoring multiple sizing fields on the same reactor
(e.g., both `volume:` and `t_res_s:`) is invalid unless the kind schema explicitly allows the
combination.

### `Reservoir`

Requires physical boundary state:

- `temperature:` — required.
- `composition:` — required.
- `pressure:` — optional, defaults to 1 atm.

Flow rates belong on edges, not on `Reservoir` nodes.

### `OutletSink`

A visualization-only terminal node with no physical state:

```yaml
- id: outlet
  OutletSink: {}
```

`OutletSink` has no required fields, may carry a `description:`, accepts inbound edges only, and
cannot be a `source:` in any connection.

---

## 8. Connection Kinds

### `MassFlowController`

Imposes a mass flow rate. Explicit `mass_flow_rate:` is valid. Omitting it (`MassFlowController: {}`
or bare `MassFlowController:`) instructs Boulder to resolve the rate by mass conservation. If the
rate cannot be uniquely determined, build fails with a conservation error.

```yaml
- id: feed_to_reactor
  MassFlowController:
    mass_flow_rate: 0.1 kg/s
  source: feed
  target: reactor
```

### `Valve`

Flow proportional to pressure drop. Requires `valve_coeff:`.

### `PressureController`

Slaved outlet device that matches flow to a primary `MassFlowController`. `master:` names the
primary MFC id. If `master:` is omitted, Boulder auto-picks the unique upstream MFC of the target
reactor; ambiguous or missing masters fail validation.

### `Wall`

Heat and/or volume coupling between two nodes. Carries thermal parameters from the kind schema.
Composite reactor unfolders (e.g. `DesignPFR`) may also generate walls automatically.

### Logical staged connection

A connection with `source:` and `target:` and **no flow-device kind key** is a logical staged
connection. It is valid only **between stages** (inter-stage); an intra-stage logical connection
fails validation.

```yaml
psr_stage:
- id: torch_to_psr
  source: torch
  target: psr
```

Semantics:

- Copies thermodynamic state `(T, P, Y)` from the source reactor outlet to the target reactor inlet.
- Does not create a Cantera flow device.
- Carries the upstream mass-flow rate by inference when conservation resolves one, or via an
  explicit `mass_flow_rate:` annotation.
- The only generic annotations are `mass_flow_rate:` and `mechanism_switch:`.
- Visualization renders it as a logical edge. Sankey omits the flow band unless a mass flow rate
  is known.

### `mechanism_switch:` on logical connections

When the upstream and downstream stages use different kinetic mechanisms, add `mechanism_switch:` to
the logical connection:

```yaml
- id: psr_to_pfr
  source: psr
  target: pfr
  mechanism_switch:
    htol: 3.0e-2
    Xtol: 1.0e-2
```

- `htol` — relative enthalpy drift tolerance (dimensionless). Exceeding it is a hard error.
- `Xtol` — dropped mole-fraction mass tolerance (dimensionless). Exceeding it is a hard error.
- `mechanism_switch:` belongs on logical connections, not on `MassFlowController`.

---

## 9. Physics Rules

- `advance_time:` is an integration horizon, not a residence time.
- `composition:` means mole fractions (`X`), normalized by Cantera. `mass_composition:` means mass
  fractions (`Y`). They are mutually exclusive.
- Use unit-bearing literals: `300 K`, `1 bar`, `1 L`, `0.1 kg/s`, `1 ms`.
- `htol` and `Xtol` are dimensionless and remain bare numbers.
- Cycle detection applies to the stage DAG only. Intra-stage reactor cycles (recycles via real flow
  devices) are allowed.
- Intra-stage nodes should use one coherent mechanism. Cross-mechanism remapping belongs at a stage
  boundary on a logical connection.

---

## 10. Valid Examples

### Single-stage network

```yaml
network:
- id: inlet
  Reservoir:
    temperature: 300 K
    pressure: 1 atm
    composition: CH4:1

- id: reactor
  IdealGasReactor:
    volume: 1 L

- id: inlet_to_reactor
  MassFlowController:
    mass_flow_rate: 0.1 kg/s
  source: inlet
  target: reactor
```

### Staged network with logical handoff

```yaml
stages:
  torch_stage:
    mechanism: gri30.yaml
    solve: advance
    advance_time: 1 ms
  psr_stage:
    mechanism: gri30.yaml
    solve: advance_to_steady_state

torch_stage:
- id: inlet
  Reservoir:
    temperature: 300 K
    composition: CH4:1
- id: torch
  IdealGasReactor:
    volume: 1 L
- id: inlet_to_torch
  MassFlowController:
    mass_flow_rate: 0.1 kg/s
  source: inlet
  target: torch

psr_stage:
- id: psr
  IdealGasReactor:
    volume: 5 L
- id: torch_to_psr
  source: torch
  target: psr
```

### Logical handoff with explicit flow annotation

```yaml
psr_stage:
- id: torch_to_psr
  source: torch
  target: psr
  mass_flow_rate: 0.1 kg/s
  mechanism_switch:
    htol: 3.0e-2
    Xtol: 1.0e-2
```

### Batch reactor with required `initial:`

```yaml
network:
- id: batch
  IdealGasReactor:
    volume: 1 L
    initial:
      temperature: 1000 K
      pressure: 1 atm
      composition: CH4:1, O2:2, N2:7.52
```

### Downstream const-pressure reactor with operating pressure

```yaml
psr_stage:
- id: psr
  DesignPSR:
    pressure: 1.3 bar
    t_res_s: 1 ms
- id: torch_to_psr
  source: torch
  target: psr
```

### Visualization-only outlet sink

```yaml
network:
- id: outlet
  OutletSink: {}
```

---

## 11. Invalid Examples

### STONE v1 shape — rejected

```yaml
nodes:
- id: reactor
  IdealGasReactor: {}

connections: []
```

*Error: STONE v1 detected. Migrate to STONE v2. See STONE_SPECIFICATIONS.md.*

### Mixed `stages:` and `network:` — rejected

```yaml
stages:
  stage_a:
    solve: advance
    advance_time: 1 ms

network: []

stage_a: []
```

*Error: `stages:` and `network:` are mutually exclusive.*

### Missing dynamic stage block — rejected

```yaml
stages:
  stage_a:
    solve: advance
    advance_time: 1 ms
```

*Error: Stage 'stage_a' declared in `stages:` but no matching top-level block found.*

### Undeclared dynamic stage block — rejected

```yaml
stages:
  stage_a:
    solve: advance
    advance_time: 1 ms

stage_a: []
stage_b: []
```

*Error: Top-level block 'stage_b' has no matching entry in `stages:`.*

### Connection with incomplete endpoints — rejected

```yaml
network:
- id: incomplete_edge
  MassFlowController:
    mass_flow_rate: 0.1 kg/s
  source: inlet
```

*Error: Connection 'incomplete_edge' has `source:` but no `target:`.*

### Downstream reactor with operating state — rejected

```yaml
stages:
  stage_a:
    solve: advance
    advance_time: 1 ms
  stage_b:
    solve: advance
    advance_time: 1 ms

stage_a:
- id: upstream
  IdealGasReactor:
    initial:
      temperature: 1200 K
      composition: CH4:1

stage_b:
- id: downstream
  IdealGasReactor:
    temperature: 1200 K
    composition: CH4:1
- id: upstream_to_downstream
  source: upstream
  target: downstream
```

*Error: Reactor 'downstream' declares top-level `temperature:` which is invalid for const-volume
kinds. Use `initial:` for seeding, or omit — the state comes from `upstream_to_downstream`.*

### Inline inlet port — rejected

```yaml
network:
- id: reactor
  IdealGasReactor:
    volume: 1 L
    inlet:
      from: inlet
      mass_flow_rate: 0.1 kg/s
```

*Error: Inline `inlet:` / `outlet:` ports are not valid in STONE v2. Author the edge as an
explicit connection item in the same block. See STONE_SPECIFICATIONS.md.*

---

## 12. Historical STONE v1 (for reference only)

STONE v1 used flat top-level `nodes:` and `connections:` lists, with each node carrying a
`group:` field to assign it to a stage declared under `groups:`:

```yaml
# STONE v1 — historical, no longer accepted
groups:
  torch_stage:
    stage_order: 1
    mechanism: gri30.yaml
    solve: advance
    advance_time: 1.0e-3

nodes:
- id: upstream
  Reservoir:
    group: torch_stage
    temperature: 300.0
    composition: CH4:1

connections:
- id: upstream_to_torch
  MassFlowController:
    mass_flow_rate: 0.005440
  source: upstream
  target: torch
```

Boulder rejects v1 files with an actionable error message pointing to this document.
