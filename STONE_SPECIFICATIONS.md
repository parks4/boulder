# STONE v2 Specification

**STONE** — Structured Type-Oriented Network Expressions — is the YAML dialect Boulder uses to
describe Cantera reactor networks. This document is the normative contract for **STONE v2**, the
current authored format.

For a quick introduction and worked examples, see `docs/stone.rst` (online) or `configs/README.md`.

______________________________________________________________________

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

______________________________________________________________________

## 2. Allowed Top-Level Keys

```
metadata   phases   settings   stages   network   export   sweeps   scenarios
continuation   signals   bindings   scopes
```

Dynamic stage block names (declared under `stages:`) are also allowed at the top level.

**Reserved names that cannot be used as stage ids:** `metadata`, `phases`, `settings`, `stages`,
`network`, `nodes`, `connections`, `signals`, `bindings`, `scopes`, `continuation`.

The `signals:`, `bindings:`, and `scopes:` blocks form Boulder's **causal layer** — a declarative
way to express time-varying drivers, state-coupled forcing, and trajectory observers in the YAML.
They are documented in full in Section 8 (Causal Layer).

______________________________________________________________________

## 3. Common Sections

### `metadata:`

A mapping for documentation and provenance fields. Key fields: `title`, `description`,
`gui_app_title` (optional short label for the web UI header; defaults to `Boulder`),
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

#### `settings.solver:` — global integrator defaults

An optional `solver:` sub-block under `settings:` sets default integrator knobs applied to every
stage unless the stage overrides them with its own `solver:` block (see Stage metadata below).

```yaml
settings:
  solver:
    mode: steady                    # "steady" | "transient" — explicit label (optional; auto-derived)
    kind: advance_to_steady_state   # integrator kind (see table below)
    rtol: 1.0e-9                    # relative tolerance (default 1e-6)
    atol: 1.0e-15                   # absolute tolerance (default 1e-8)
    max_time_step: 1.0e-5           # optional: maximum integrator time step (s)
    max_steps: 10000                # optional: maximum integrator steps per advance
    initial_time_reset: false       # optional: reset integrator clock to 0 before solve
```

##### `solver.mode` — steady vs transient label

`solver.mode` is an optional, human-readable label (`steady` or `transient`) that summarises which
class of solver is active. It is surfaced in the Boulder GUI (as a badge and as a toggle that
adapts the visible control fields) and in generated scripts.

**When `mode:` is absent**, Boulder auto-derives it from `kind:`:

| `solver.kind` | Implied `solver.mode` | Relevant extra keys |
|-----------------------------|-----------------------|----------------------------------------------|
| `advance_to_steady_state` | `steady` | `rtol`, `atol`, `max_steps` |
| `solve_steady` | `steady` | `rtol`, `atol`, `max_steps` |
| `advance` | `transient` | `advance_time` |
| `advance_grid` | `transient` | `grid: { start, stop, dt }` |
| `micro_step` | `transient` | `t_total`, `chunk_dt`, `max_dt` |

**When `mode:` is present** and contradicts `kind:`, a `ValueError` is raised at config-load time.
Contradiction examples: `mode: steady` with `kind: micro_step`, or `mode: transient` with
`kind: solve_steady`.

The resolved `mode` is always present in the normalised config dict (auto-filled if absent) so
downstream consumers (GUI, FMU export, generated scripts) can read it without re-deriving.

`solver.kind` controls which Cantera integrator call is used per stage:

| `kind` | Cantera call | Extra required keys |
|---|---|---|
| `advance_to_steady_state` | `network.advance_to_steady_state()` | — |
| `solve_steady` | `network.solve_steady()` | — |
| `advance` | `network.advance(advance_time)` | `advance_time` |
| `advance_grid` | loop `network.advance(t)` over a time grid | `grid` |
| `micro_step` | chunked micro-step loop + optional `reinitialize` | `t_total`, `chunk_dt`, `max_dt` |

`advance_to_steady_state` is the default when no `solver:` block is present.

`solve_steady` uses Cantera's built-in steady-state solver (more robust near extinction than
`advance_to_steady_state` for well-stirred reactor sweeps).

`advance_grid` accepts either a shorthand or an explicit time list:

```yaml
solver:
  kind: advance_grid
  grid:
    start: 0.0
    stop: 0.12         # seconds
    dt: 4.0e-4         # output time step
```

`micro_step` drives the network in small chunks and optionally reinitializes the integrator between
chunks (required when source terms change discontinuously, e.g. plasma discharge pulses):

```yaml
solver:
  kind: micro_step
  t_total: 90e-9       # total integration time (s)
  chunk_dt: 1e-9       # chunk size (s)
  max_dt: 1e-10        # maximum integrator sub-step (s)
  reinitialize_between_chunks: true   # call network.reinitialize() after each chunk
```

### `export:`

KPI functions, figure generators, calc-note targets. Consumed by `bloc.yaml_utils` and
`bloc.calc_note`. Not interpreted by Boulder core.

______________________________________________________________________

## 4. Staged Networks — `stages:`

Use `stages:` when the reactor network is solved in sequential steps (e.g. torch → PSR → PFR).

### Stage metadata

```yaml
stages:
  torch_stage:
    mechanism: gri30.yaml       # required
    solver:                     # optional; overrides settings.solver for this stage
      mode: transient           # optional: "steady" | "transient" (auto-derived from kind)
      kind: advance             # "advance_to_steady_state" | "solve_steady" | "advance"
                                #   | "advance_grid" | "micro_step"
      advance_time: 1.0e-3     # required iff kind == advance; forbidden otherwise
      rtol: 1.0e-9             # optional per-stage tolerance overrides
      atol: 1.0e-15
      max_time_step: 1.0e-5
      max_steps: 20000
      initial_time_reset: false # reset integrator clock before this stage's solve
```

**Legacy form** (deprecated, still accepted with a warning):

```yaml
stages:
  torch_stage:
    mechanism: gri30.yaml
    solve: advance              # mapped to solver.kind
    advance_time: 1.0e-3        # mapped to solver.advance_time
```

The legacy `solve:` / `advance_time:` keys at the stage level are silently promoted to
`solver: { kind: ..., advance_time: ... }` at config-load time. New files should use `solver:`.

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

______________________________________________________________________

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

______________________________________________________________________

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

______________________________________________________________________

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

### `clone:` — phase sharing between reactors

By default Boulder creates an independent copy of the Cantera `Solution` object for each reactor
(`clone: true`). Set `clone: false` only when two reactors must share the same `Solution` instance
(e.g. a `ConstPressureReactor` feeding directly from a mutated `PlasmaPhase`):

```yaml
- id: plasma_reactor
  ConstPressureReactor:
    energy: "off"
    clone: false
```

`clone: false` is only meaningful when the `Solution` carrying plasma state or custom source terms
is mutated externally between integrator steps (e.g. `micro_step` with `schedule:` callbacks).
For all other cases use the default `clone: true`.

### `energy:` — enable/disable energy equation

Applicable to `ConstPressureReactor` and `IdealGasConstPressureReactor`:

```yaml
- id: isothermal
  ConstPressureReactor:
    energy: "off"   # "on" (default) or "off"
```

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

______________________________________________________________________

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

`mass_flow_rate:` may also be a **schedule spec** (time-varying via `Func1`), a **closure** (a
Python callable bound to a reactor), or omitted entirely (mass-conservation auto-resolve). All
forms are described below.

#### `mass_flow_rate:` — schedule spec (time-varying)

The spec is converted to a Cantera `Func1` and passed to `mfc.mass_flow_rate`. The schedule fires
automatically during `micro_step` integration (no special config needed):

```yaml
- id: inlet_mfc
  MassFlowController:
    mass_flow_rate:
      func: sin              # Cantera named function
      args: [0.05, 100.0, 0.0]   # amplitude, frequency, phase
  source: inlet
  target: reactor
```

```yaml
- id: inlet_mfc
  MassFlowController:
    mass_flow_rate:
      profile: piecewise_linear
      points:             # [time_s, value_kg/s]
        - [0.0, 0.0]
        - [1e-9, 0.01]
        - [5e-9, 0.05]
        - [9e-9, 0.0]
  source: inlet
  target: reactor
```

#### `mass_flow_rate:` — closure (residence-time style)

A `closure:` spec binds the mass flow rate to a live reactor property, evaluated each integrator
step. Currently supported:

- `residence_time` — sets `mdot(t) = reactor.mass / tau_s` where `tau_s` is the target residence
  time in seconds. This is the standard PSR closure.

```yaml
- id: inlet_to_psr
  MassFlowController:
    mass_flow_rate:
      closure: residence_time
      reactor: psr          # id of the reactor whose mass is used
      tau_s: 1.0e-3         # target residence time (seconds)
  source: inlet
  target: psr
```

The `closure:` form uses a Python callable wrapper (not a `Func1`) and is compatible with all
solver kinds including `solve_steady` and `advance_to_steady_state`.

### Node `schedule:` block

Reactor nodes may carry a `schedule:` block to register time-varying source terms that are
evaluated before each `micro_step` chunk. Currently supported:

- `reduced_electric_field:` — updates `gas.reduced_electric_field` and calls
  `gas.update_electron_energy_distribution()` (required for `nanosecond_pulse_discharge`-style
  plasma simulations).

```yaml
- id: plasma_reactor
  ConstPressureReactor:
    energy: "off"
    clone: false
    schedule:
      reduced_electric_field:
        profile: piecewise_linear
        points:
          - [0.0e-9, 500.0]    # Td
          - [10.0e-9, 500.0]
          - [10.001e-9, 0.0]
          - [90.0e-9, 0.0]
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

______________________________________________________________________

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

______________________________________________________________________

## 10. Continuation Sweeps — `continuation:` block

The optional top-level `continuation:` block drives an outer loop that mutates one
parameter across sequential steady-state (or transient) solves, collecting a trajectory of results.
This is the STONE equivalent of the combustor extinction sweep in `combustor.py`.

```yaml
continuation:
  parameter: connections.inlet_mfc.mass_flow_rate   # dotted path to target attribute
  update:
    multiply: 0.9     # scale factor per iteration  (alternatively: set: <value>, list: [...])
  until:
    reactor_T_below: 500.0   # stop when any reactor T drops below this (K)
    max_iters: 200            # hard cap; at least one of until/max_iters required
```

`parameter` dotted path resolution:

- `connections.<id>.mass_flow_rate` → `converter.connections[<id>].mass_flow_rate`
- `nodes.<id>.volume` → `converter.reactors[<id>].volume`

`update` modes:

- `multiply: <factor>` — current value × factor each iteration
- `set: <value>` — set to a fixed value
- `list: [v1, v2, ...]` — iterate through explicit values

`until` predicate (all optional; first matched stops the loop):

- `reactor_T_below: <K>` — any non-Reservoir reactor T < value
- `reactor_T_above: <K>` — any non-Reservoir reactor T > value
- `max_iters: <N>` — maximum iteration count (always required as safety cap)

______________________________________________________________________

## 11. Valid Examples

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

______________________________________________________________________

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

______________________________________________________________________

## 8. Causal Layer — `signals:`, `bindings:`, `scopes:`

Boulder's causal layer lets you express time-varying drivers, state-coupled forcing and trajectory
observers declaratively in the YAML, without embedding Python code. It is analogous to a minimal
Simulink block diagram: signals are *source blocks*, bindings are *wires*, and scopes are
*output probes*.

All three keys are optional. If absent, the existing inline forms (`schedule:`, `closure:`) still
work unchanged.

______________________________________________________________________

### `signals:` — driver source blocks

A top-level list of named signal definitions. Each entry has an `id:` and exactly one **source-kind
key**:

```yaml
signals:
  - id: pulse
    Gaussian: { peak: 1.9e-19, center: 24e-9, fwhm: 7.06e-9 }

  - id: tau_sweep
    PiecewiseLinear:
      points: [[0.0, 0.1], [5.0, 0.05], [10.0, 0.001]]

  - id: inlet_temp
    Sine: { amplitude: 50.0, frequency: 1.0, phase: 0.0, offset: 600.0 }

  - id: double_pulse
    Sum: { inputs: [pulse, pulse] }
```

#### Source-block reference

| Kind | Required args | Description |
|-------------------|--------------------------------------------------------|------------------------------------------------------|
| `Constant` | `value` | Fixed scalar (cf. YAML scalar `mass_flow_rate: 0.1`) |
| `Sine` | `amplitude`, `frequency` (Hz), `phase` (rad), `offset`| `A·sin(2π·f·t + φ) + offset` |
| `Gaussian` | `peak`, `center` (s), `fwhm` (s) | Wraps `ct.Func1("Gaussian", [peak, center, fwhm])` |
| `Step` | `t_step`, `value_before`, `value_after` | Heaviside step at `t_step` |
| `Ramp` | `t_start`, `t_end`, `value_start`, `value_end` | Linear ramp; constant outside the interval |
| `PiecewiseLinear` | `points: [[t0, v0], [t1, v1], ...]` | Wraps `ct.Func1("tabulated", ...)` |
| `FromCSV` | `path`, `time_col`, `value_col`, `interp: linear` | Read from CSV file at build time |
| `Sum` | `inputs: [signal_id, ...]` | Element-wise sum of prior signals |
| `Gain` | `input: signal_id`, `k` | `k * signal` |
| `Integrator` | `input: signal_id`, `x0: 0.0` | `∫ signal dt + x0` (state held by the solver loop) |

**Evaluation order**: sources are built first (in declaration order), then combinators
(`Sum`, `Gain`, `Integrator`) which may reference prior signal ids. Forward references are an
error.

______________________________________________________________________

### `bindings:` — wires from signals to network targets

A top-level list of binding rules. Each entry has `source:` (a signal id) and `target:` (a dotted
path into the network):

```yaml
bindings:
  - source: pulse
    target: nodes.r1.reduced_electric_field

  - source: tau_sweep
    target: connections.inlet_mfc.tau_s

  - source: inlet_temp
    target: nodes.r1.temperature     # future: not yet implemented
```

#### Binding target grammar

| Target path | Effect |
|------------------------------------------|---------------------------------------------------------------|
| `connections.<id>.mass_flow_rate` | Sets `MassFlowController.mass_flow_rate = Func1` |
| `connections.<id>.tau_s` | Updates the `residence_time` closure denominator each step |
| `nodes.<id>.reduced_electric_field` | Fires a micro_step chunk callback calling `phase.reduced_electric_field = signal(t)` |
| `continuation.parameters.<name>` | Exposes the signal as a continuation update source |

Unknown or unsupported target paths raise a `ValueError` at build time (no silent fallback).

**Update cadence**: bindings to `nodes.<id>.reduced_electric_field` fire at micro_step chunk
boundaries (matching the upstream `sim.reinitialize()` pattern). Bindings to MFC `mass_flow_rate`
are applied as a persistent `ct.Func1` and evaluated by Cantera's integrator at each internal step.

______________________________________________________________________

### `scopes:` — trajectory observers

A top-level list of observer definitions. Each entry captures the time evolution of one variable:

```yaml
scopes:
  - variable: nodes.combustor.T
    output: true          # expose as a result column in BoulderRunner.scopes

  - variable: nodes.r1.X[e]
    every: 10             # sample every 10 solver steps

  - variable: connections.inlet_mfc.mass_flow_rate
    file: mdot_history.csv   # flush to CSV at end of stage
```

#### Scope fields

| Field | Type | Default | Description |
|------------|---------|---------|-------------------------------------------------------------|
| `variable` | string | — | Dotted path (same grammar as bindings, read side) |
| `output` | bool | `false` | Include this variable in `BoulderRunner.scopes` DataFrame |
| `every` | int | 1 | Sampling stride (1 = every step, 10 = every 10th step) |
| `file` | string | none | CSV path; written at end of the stage's solve |

`BoulderRunner.scopes` returns a `dict[str, pandas.DataFrame]` keyed by scope `variable`.
Each DataFrame has columns `t` and `value`.

______________________________________________________________________

### Relationship to inline forms

The existing inline driver syntax continues to work. The causal layer is additive:

| Inline form (still valid) | Causal-layer equivalent |
|--------------------------------------------------------|------------------------------------------------------------------|
| `mass_flow_rate: { schedule: { func: gaussian, ... } }` | `signals: [Gaussian ...]` + `bindings: [...mass_flow_rate]` |
| `mass_flow_rate: { closure: residence_time, tau_s: 0.1 }` | `bindings: [... tau_s]` with a `Constant` signal |
| `schedule: { reduced_electric_field: { ... } }` on node | `signals: [...]` + `bindings: [... reduced_electric_field]` |

No deprecation warnings at this time; consolidation is a future option.

______________________________________________________________________

### Worked examples — vendored Cantera scripts

These three examples correspond to the scripts in `docs/cantera_examples/` and show how each
upstream Cantera pattern maps to the causal layer.

#### `nanosecond_pulse_discharge.py` → `micro_step` + `Gaussian` signal

The upstream script applies a Gaussian-shaped electric field pulse (`gaussian_EN`) to a
`ConstPressureReactor` with `energy: "off"` (plasma mode), advancing in 1 ns chunks with
`sim.reinitialize()` between chunks.

```yaml
# derived_via: ast_match
settings:
  solver:
    kind: micro_step
    t_total: 90e-9       # total pulse window
    chunk_dt: 1e-9       # 1 ns chunks
    max_dt: 1e-10        # internal sub-step
    reinitialize_between_chunks: true

# derived_via: ast_match
signals:
  - id: gaussian_EN
    kind: Gaussian
    peak: 1.9e-19      # 190 Td peak E/N
    center: 24e-9      # pulse centre at 24 ns
    fwhm: 7.06e-9      # full-width at half maximum

# derived_via: ast_match
bindings:
  - source: gaussian_EN
    target: nodes.ConstPressureReactor_0.reduced_electric_field

network:
  - id: ConstPressureReactor_0
    ConstPressureReactor:
      energy: "off"
      # clone: false — gas phase shared with reservoir
```

The binding fires at each micro_step chunk boundary, calling
`phase.reduced_electric_field = gaussian_EN(t)` and `phase.update_electron_energy_distribution()`.

______________________________________________________________________

#### `combustor.py` → `solve_steady` + `closure` + `continuation:`

The upstream script uses a residence-time closure (`def mdot(t): return reactor.mass / tau`) on
the `MassFlowController` and sweeps `residence_time` down while the reactor temperature stays above
500 K.

```yaml
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
```

The `continuation:` block mirrors the `while combustor.T > 500: sim.solve_steady(); tau *= 0.9` loop.

______________________________________________________________________

#### `reactor2.py` → `advance_grid`

The upstream script advances two coupled reactors (`r1`: argon, `r2`: methane/air) over 300 equal
time steps of `4e-4 s` with a `for n in range(300): sim.advance(time)` loop.

```yaml
# derived_via: ast_match
settings:
  solver:
    kind: advance_grid
    grid:
      start: 0.0
      stop: 0.12       # 300 steps × 4e-4 s
      dt: 4.0e-4

network:
  - id: Argon partition
    IdealGasReactor: { ... }
    mechanism: air.yaml

  - id: Reacting partition
    IdealGasReactor: { ... }

  # Piston wall between the two reactors
  - id: Piston
    Wall:
      A: 1.0
      K: 5.0e-5
      U: 100.0
    source: Reacting partition
    target: Argon partition
```

No `signals:` or `bindings:` are needed: `reactor2` has no time-varying drivers.

______________________________________________________________________

### `BoulderRunner` public surface (FMU data-shape contract)

After calling `runner.build()` or `runner.solve()`, two properties expose the causal layer
to downstream consumers such as the GUI, co-simulation masters, and the FMU Path A skeleton
described in `FMI_FMU_EXPORT.md`:

| Property | Type | Description |
|-------------------------------|-----------------------------------|-----------------------------------------------------------------|
| `runner.exposed_inputs` | `dict[str, dict]` | Signals **not** referenced as `source` in any `bindings:` entry |
| `runner.scopes` | `dict[str, pandas.DataFrame]` | Recorded scope variables; each DataFrame has columns `t`, `value` |

**`exposed_inputs`** is the FMI-3.0 input variable list: each key is the signal `id`, each value
is the raw spec dict from `signals:`. A signal whose `id` appears as `source` in *any* `bindings:`
entry is considered wired to an internal network target and is therefore absent from this dict.

```python
runner = BoulderRunner.from_yaml("nanosecond.yaml").build()

# Signals that an FMU master could override at each doStep:
for sig_id, spec in runner.exposed_inputs.items():
    print(sig_id, spec["kind"])   # e.g. "gaussian_EN Gaussian"

# Recorded trajectories per scope variable:
df = runner.scopes["nodes.r1.T"]   # columns: t, value
df.plot(x="t", y="value")
```

No FMU code is generated in this release; these properties define the data shape that
`boulder.fmi.BoulderFMU` (Path A) will consume. See `FMI_FMU_EXPORT.md` for the full roadmap.

______________________________________________________________________

## 9. Top-level `continuation:` block

See the Continuation section in Section 3 and the worked examples in
`docs/cantera_upstream_examples.rst`.

______________________________________________________________________

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
