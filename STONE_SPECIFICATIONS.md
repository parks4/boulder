# STONE 2.x Specification

**STONE** — Structured Type-Oriented Network Expressions — is the YAML dialect Boulder uses to
describe Cantera reactor networks. This document is the normative contract for **STONE 2.x**
(informally "STONE v2": the `network:` / `stages:` shape), the current authored format. The exact
format version is `metadata.stone_version` (Section 1).

For a quick introduction and worked examples, see `docs/stone.rst` (online) or `configs/README.md`.

______________________________________________________________________

## 1. Format Version and Dialect Detection

### Dialect (shape)

Boulder infers the dialect from the top-level shape:

| Shape | Dialect |
|---|---|
| Top-level `network:` list | STONE 2.x ("v2") — single stage |
| Top-level `stages:` mapping | STONE 2.x ("v2") — staged |
| Top-level `nodes:`, `connections:`, or `groups:` | STONE 1.x ("v1", historical) — **rejected** |
| None of the above | Invalid — error |

Files that mix `stages:` and `network:` at the same level are rejected.

### Format version — `metadata.stone_version`

```yaml
metadata:
  stone_version: "2.1"   # quoted string, MAJOR.MINOR
```

- Versioned independently of the Boulder package version. **MAJOR** bumps when old files stop
  loading. **MINOR** bumps when the STONE vocabulary or semantics change but old files still load.
  Boulder releases that do not touch the format keep writing the previous value, so a file written
  by a later Boulder still loads in an earlier one when the format did not change in between.
- Always a **quoted string**: unquoted `2.10` is the YAML float `2.1`.
- The field is optional on input. A file without it is a pre-versioned STONE 2.x file.
- Boulder rewrites it to its own `boulder.config.STONE_FORMAT_VERSION` on every load, so any YAML
  Boulder writes (YAML pane sync and Download, `/api/configs/export`, `sim2stone`) carries the
  current value. `metadata.version` is unrelated: it is the user's own document revision.

Reader rules (Boulder at `STONE_FORMAT_VERSION = M.m`, file at `stone_version = X.y`):

| File | Behaviour |
|---|---|
| absent | accepted silently, stamped `M.m` |
| `X == M`, `y <= m` | accepted silently |
| `X == M`, `y > m` | accepted with a warning (written by a newer Boulder; unknown keys fail validation) |
| `X != M` | accepted with a warning; the 1.x shape is still a hard error |
| not `MAJOR.MINOR` | accepted with a warning, treated as `M.m` |

### Compatibility promise

- Within a MAJOR, a reader at `M.y` reads every file written at `M.x`, `x <= y`.
- Removing or renaming a key within a MAJOR requires a **load-time migration**: the old key is
  accepted, converted or discarded, and reported as a warning — never a hard error. The current
  migration table is `boulder.config.LEGACY_METADATA_KEYS`, applied by `migrate_stone_config`.
- A change that makes old files stop loading bumps the STONE MAJOR. This is independent of the
  Boulder package version, which follows its own semver history.
- To convert an old file: upload it in the Boulder GUI, open the YAML pane (the banner lists what was
  migrated) and Download. Comments and unit strings are preserved.

______________________________________________________________________

## 2. Allowed Top-Level Keys

```
metadata   phases   settings   stages   network   export   scenarios   scenarios_sweep
signals   bindings   scopes
```

`scenarios:` and `scenarios_sweep:` declare inline run-set variations (Section 14). Boulder validates
and passes them through; a host's reporting/expansion layer consumes them. (The legacy list-valued
top-level `scenarios:` — `[{id, set, metadata}, ...]` — is removed; only the mapping form
`scenarios: {<id>: <overlay>}` is accepted.)

**Legacy keys, still loaded but warned about:** `sweep:` / `sweeps:` (former spellings of
`scenarios_sweep:`, renamed on load) and `continuation:` (Section 10 — only the headless
`BoulderRunner.run_continuation` executes it; Run Sweep runs its `scenarios_sweep.while` form).

Dynamic stage block names (declared under `stages:`) are also allowed at the top level.

**Reserved names that cannot be used as stage ids:** `metadata`, `phases`, `settings`, `stages`,
`network`, `nodes`, `connections`, `signals`, `bindings`, `scopes`, `continuation`.

The `signals:`, `bindings:`, and `scopes:` blocks form Boulder's **causal layer** — a declarative
way to express time-varying drivers, state-coupled forcing, and trajectory observers in the YAML.
They are documented in full in Section 8 (Causal Layer).

______________________________________________________________________

## 3. Common Sections

### `metadata:`

A mapping for documentation and provenance fields. Key fields: `stone_version` (format version,
written by Boulder — Section 1), `title`, `description`, `gui_app_title` (optional short label for
the web UI header; defaults to `Boulder`), `author`, `date`, `project`, `version` (the user's own
document revision). See `boulder/validation.py:MetadataModel` for the full vocabulary. Removed keys
(`scenario_id`, `scenario_name`) are discarded with a warning on load.

### `phases:`

Mechanism registry. Maps phase aliases to Cantera mechanism files:

```yaml
phases:
  gas:
    mechanism: gri30.yaml
  fuel:
    mechanism: h2o2.yaml
```

A `mechanism:` value in a stage or node may be a phase alias (`gas`, `fuel`) or a raw mechanism
filename (`gri30.yaml`). Resolution order: **node** > **stage** > `phases.gas.mechanism` >
Boulder default.

### `settings:`

Simulation-level settings passed to the solver and post-processing. Schema is open; see individual
plugin documentation for recognized keys.

#### `settings.staged:` — staged-solver behaviour

Stream-point reservoirs (P&ID diamonds at each inter-stage boundary) are always
synthesised by the staged solver. A `ct.Reservoir` and one inlet
`MassFlowController` per downstream target are created at every stage boundary so
that all flow rates are honoured at solve time and the full topology is visible to
the Sankey and Network visualisations.

The former `settings.staged.stream_reservoirs` YAML key is no longer recognised;
remove it from any existing configs. The deprecated code alias
`interface_reservoirs` is still accepted by `solve_staged()` for backward
compatibility in tests.

> **Plugin authors — `post_build` topology constraint.** Boulder's `post_build` hooks
> receive a *per-stage subset* dict `{"nodes": [...], "connections": [...]}` that is a
> copy of the stage slice, not the full top-level config. Appending new node or connection
> dicts inside a `post_build` hook does not make them visible to the frontend graph (they
> are absent from `updated_nodes` / `updated_connections` in the SSE `complete` event).
> To add topology that must appear in the visual graph, use a `ReactorUnfolder` (runs at
> normalize-time) or a reactor builder that injects dicts into `config["nodes"]` /
> `config["connections"]` before returning. See `ARCHITECTURE.md` — *`post_build` hooks —
> topology constraint* for the full explanation.

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

##### `solver.axis` — time vs. distance marching

`solver.axis` is an optional label (`"time"` | `"distance"`, default `"time"`) naming the
independent variable an `advance_grid` / `micro_step` solve marches over. It exists for stages
built around a `FlowReactor` (see Node Kinds below): a plug-flow reactor is integrated along
**distance**, not time, and Cantera's `ReactorNet.advance(x)` / `.step()` dispatch on whichever
independent variable the network's reactors imply — `ReactorNet.distance` for a `FlowReactor`
network, `ReactorNet.time` for every other reactor kind. `grid: { start, stop, dt }` keeps the
same shape either way; `dt` is a step in the axis's own unit (s for `time`, m for `distance`).

```yaml
solver:
  kind: advance_grid
  axis: distance      # grid values below are meters, not seconds
  grid:
    start: 0.0
    stop: 0.003        # 3 mm catalyst bed length
    dt: 6.0e-5
```

`axis: distance` is opt-in and per-stage: it never changes the default (`time`) behaviour of
existing `advance_to_steady_state` / `advance` / time-grid stages. A stage's recorded trajectory
is tagged accordingly so the frontend plots it against position (m) instead of time (s) — see
`FlowReactor` in Node Kinds.

### `export:`

KPI functions, figure generators, calc-note targets. Consumed by downstream
host packages. Not interpreted by Boulder core.

______________________________________________________________________

## 4. Staged Networks — `stages:`

Use `stages:` when the reactor network is solved in sequential steps (e.g. torch → PSR → PFR).

### Stage metadata

```yaml
stages:
  torch_stage:
    mechanism: gri30.yaml       # required
    solver: advance             # solver kind — one of the values in the table below
    advance_time: 1.0e-3        # required iff solver == advance; forbidden otherwise
```

`solver:` is a scalar string naming the integrator kind. Valid values mirror `solver.kind` in
`settings.solver:` (see table above): `advance_to_steady_state`, `solve_steady`, `advance`,
`advance_grid`, `micro_step`.

When `solver: advance` is used, `advance_time:` must appear at the same level as `solver:`.

For per-stage tolerance overrides or `advance_grid` / `micro_step` parameters, use the block form
under `settings.solver:` or pass them in the extended block form:

```yaml
stages:
  torch_stage:
    mechanism: gri30.yaml
    solver:                     # block form — all solver.* keys accepted here
      kind: advance
      advance_time: 1.0e-3
      rtol: 1.0e-9
      atol: 1.0e-15
      max_time_step: 1.0e-5
      max_steps: 20000
      initial_time_reset: false
```

**Deprecated key** (still accepted with a warning, rename to `solver:`):

```yaml
stages:
  torch_stage:
    mechanism: gri30.yaml
    solve: advance              # deprecated — rename to solver:
    advance_time: 1.0e-3
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
| Const-pressure (`IdealGasConstPressureReactor`, `CustomPSR`) | top-level operating constraint | invalid unless kind defines isothermal mode |

Top-level reactor `temperature:` is invalid unless the kind schema explicitly defines a
fixed-temperature model option.

### Sizing

Each reactor kind defines one sizing basis. Authoring multiple sizing fields on the same reactor
(e.g., both `volume:` and `t_res_s:`) is invalid unless the kind schema explicitly allows the
combination.

#### `t_res_s:` — residence-time sizing (PSR / well-mixed reactors)

When a reactor node declares `t_res_s:` (seconds) and no explicit `volume:`, Boulder sets volume
after mass-flow conservation at build time:

```text
V = t_res_s × ṁ_in / ρ
```

where `ṁ_in` is the sum of resolved incoming `MassFlowController` rates (kg/s) and `ρ` is the
reactor gas density at sizing time. Hydraulic residence time at startup is therefore approximately
`t_res_s`.

PSR / mixing stages should use `solver.kind: advance_to_steady_state` (the default). Do not
duplicate `t_res_s` as `advance_time` on the stage — `advance_time` is an integration horizon, not
a residence-time substitute (see Physics Rules).

### `clone:` — phase sharing between reactors

By default each reactor gets its own independent Cantera `Solution` (`clone: true`). Boulder
builds that phase from the mechanism parsed once per process rather than through Cantera's
`clone=True` (which re-installs every reaction and forgets the mechanism file): same isolation,
a fraction of the cost on a large mechanism. Reservoirs get a reaction-free phase, since they never
integrate chemistry. Set `clone: false` only when two reactors must share the same `Solution`
instance (e.g. a `ConstPressureReactor` feeding directly from a mutated `PlasmaPhase`):

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

### `FlowReactor`

A steady-state plug-flow reactor with constant cross-sectional area, integrated along **distance**
(see `solver.axis: distance` above), not time. Pair with `solver.kind: advance_grid` (or
`micro_step`) and `axis: distance` — Cantera's `ReactorNet.advance(x)` / `.distance` dispatch on
the independent variable implied by the network's reactors.

State placement follows the same `initial:` rules as other reactor kinds (top-level `temperature:`
/ `composition:` / `mass_composition:` are invalid). Sizing is by `area:` + `mass_flow_rate:`, not
`volume:` / `t_res_s:`.

| Property | Required | Notes |
|---|---|---|
| `area:` | No | Cross-sectional area (m²). Changing it rescales flow speed to keep `mass_flow_rate` constant. |
| `mass_flow_rate:` | No | Mass flow rate (kg/s) — a plain float, unlike `MassFlowController.mass_flow_rate` there is no Func1/schedule form. |
| `surface_area_to_volume_ratio:` | No | Catalyst surface area per unit bed volume (1/m); only meaningful alongside `surface:`. |
| `energy:` | No | `"on"` (default) or `"off"` — same convention as other energy-capable kinds. |
| `surface:` | No | Attaches a `FlowReactorSurface` (catalytic surface chemistry) — see below. |

```yaml
- id: pfr
  FlowReactor:
    initial:
      temperature: 1073.15 K
      pressure: 1 atm
      composition: "CH4:1, O2:1.5, AR:0.1"
    area: 1.0e-4 m**2
    mass_flow_rate: 1.7278e-05 kg/s
    surface_area_to_volume_ratio: 300.0
    energy: "off"
```

### `FlowReactorSurface` — `surface:` property on a `FlowReactor` node

A `FlowReactor`'s `surface:` property attaches a `ct.ReactorSurface` (Cantera's general
surface-chemistry class — there is no separate `ct.FlowReactorSurface` in the Cantera API) for
catalytic reactions at the wall. Boulder builds the surface `Interface` phase **first** and derives
the reactor's actual gas phase from `surface.adjacent[...]` — mirroring upstream Cantera's own
`surf_pfr.py` pattern (`surf = ct.Interface(...); gas = surf.adjacent['gas']`) — since the interface
kinetics reference that specific adjacent-phase object.

| Property | Required | Notes |
|---|---|---|
| `phase:` | Yes | The `Interface` phase name within the mechanism file (e.g. `Pt_surf`). |
| `mechanism:` | No | Surface mechanism file. Defaults to the `FlowReactor` node's own `mechanism:` — the common case is one file holding both the gas and surface phases. |
| `site_density:` | No | Overrides the phase's default site density (mol/m²). |
| `initial.coverages:` | No | `"species:fraction, species:fraction, ..."` — same string grammar as gas `composition:`. |

```yaml
    surface:
      phase: Pt_surf
      initial:
        coverages: "PT(S): 0.7, O(S): 0.2, CO(S): 0.1"
```

### `Reservoir`

Requires physical boundary state:

- `temperature:` — required.
- `composition:` — required.
- `pressure:` — optional, defaults to 1 atm.

Flow rates belong on edges, not on `Reservoir` nodes.

### `OutletSink`

**Deprecated.** Prefer inter-stage **stream-point diamonds** (`{source}_outlet`
Reservoirs synthesised by the staged solver and refreshed by
`_update_stream_point`). `OutletSink` remains for legacy single-stage diagrams
only and will be removed in a future STONE version.

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
Composite reactor unfolders (e.g. a plugin-defined PFR kind) may also generate walls automatically.

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

- `advance_time:` is an integration horizon, not a residence time. Size PSR volume with `t_res_s:`
  on the reactor node; integrate open PSR stages to steady state unless you deliberately need a
  transient horizon.
- `composition:` means mole fractions (`X`), normalized by Cantera. `mass_composition:` means mass
  fractions (`Y`). They are mutually exclusive.
- Use unit-bearing literals: `300 K`, `1 bar`, `1 L`, `0.1 kg/s`, `1 ms`.
- `htol` and `Xtol` are dimensionless and remain bare numbers.
- Cycle detection applies to the stage DAG only. Intra-stage reactor cycles (recycles via real flow
  devices) are allowed.
- Intra-stage nodes should use one coherent mechanism. Cross-mechanism remapping belongs at a stage
  boundary on a logical connection.

______________________________________________________________________

## 10. Continuation Sweeps — `continuation:` block (legacy)

> **Legacy.** `continuation:` is still accepted (with a warning on load) but only the headless
> `BoulderRunner.run_continuation` executes it — its results never reach the run-set store or the
> Scenario pane. The run-set form of the same loop is `scenarios_sweep.while` (Section 14), which Run
> Sweep executes point by point with `initial: from_previous`; `sim2stone` emits that form.

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
    solver: advance
    advance_time: 1 ms
  psr_stage:
    mechanism: gri30.yaml
    solver: advance_to_steady_state

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
  # CustomPSR is an example of a reactor class provided by a plugin.
  CustomPSR:
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
    solver: advance
    advance_time: 1 ms

network: []

stage_a: []
```

*Error: `stages:` and `network:` are mutually exclusive.*

### Missing dynamic stage block — rejected

```yaml
stages:
  stage_a:
    solver: advance
    advance_time: 1 ms
```

*Error: Stage 'stage_a' declared in `stages:` but no matching top-level block found.*

### Undeclared dynamic stage block — rejected

```yaml
stages:
  stage_a:
    solver: advance
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
    solver: advance
    advance_time: 1 ms
  stage_b:
    solver: advance
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

## 12. Historical STONE 1.x ("v1", for reference only)

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

______________________________________________________________________

## 13. Result serialization schema (the result store's `<scenario_id>.h5`)

A computed result is persisted in **one** composite-HDF5 format (`boulder/payload_store.py`), used by
every entry of the result store (`boulder/scenario_store.py`). This is an on-disk contract, not part
of the YAML a user writes — documented here alongside the config schema so tooling recognizes it.

### Core encoding — three tiers (per reactor series)

| Tier | When | How stored | Notes |
|---|---|---|---|
| `solution` | state-shaped (`T`,`P`,`X`); species ⊆ mechanism; `X` rows sum to 1 ± 1e-6 | Cantera `SolutionArray` group (`r0`,`r1`,…) | `Y` derived on load; every per-state numeric column (`t`, `x`, …) is a SolutionArray `extra` |
| `arrays` | state-shaped but mechanism can't represent it, or `X` not normalized | binary HDF5 datasets `T`,`P` (1D), `X`/`Y` (2D), `extra__<k>` per extra column, + `species_names` attr | no `Solution` needed to read |
| `raw` | not state-shaped (no `T`/`P` lists or no `X` dict) | verbatim in the JSON blob | lossless |

A **spatial PFR profile is a state sequence** (its `x` is just another per-state column) and is stored
natively in `solution`/`arrays` — not raw. Per-reactor fields that are *not* per-state columns — flags
(`is_spatial`, `is_psr`, `is_residence`) and off-shape arrays (`fbs_convergence`, which is
per-FBS-iteration) — ride in the reactor's `meta` (below) and are merged back on load, so the original
series is reproduced exactly.

### `payload_json` dataset

A UTF-8 JSON string dataset (not an attribute — no ~64 KB cap) holding the rest of the
`SimulationResults` (`times`, `reactor_reports`, `connection_reports`, `summary`, `code_str`,
`sankey_links`, `sankey_nodes`, `updated_nodes`, `updated_connections`) plus a `reactors_index`:

```jsonc
"reactors_index": {
  "<id>": { "kind": "solution", "group": "r0", "extra_keys": ["t"],      "meta": {"is_residence": true} },
  "<id>": { "kind": "arrays",   "group": "r1", "extra_keys": ["t", "x"], "meta": {"is_spatial": true, "fbs_convergence": [12.0, 3.0]} },
  "<id>": { "kind": "raw",      "series": { ... } }
}
```

The config snapshot is **not** here — for the cache it lives in `meta.json` so a snapshot scan need
not restore numerics.

### Root attributes & versioning

`schema_version` (== `payload_store.PAYLOAD_SCHEMA`), `mechanism` (resolved abs path, or bundled
name), `mechanism_sha256` (diagnostic; the cache fingerprint is the correctness guard), `mechanism_name`.
`result_cache.CACHE_VERSION` gates cache entries (mismatch ⇒ silent miss + recompute). These version
the result store only; the YAML format version is `metadata.stone_version` (Section 1).

### One file per run-set entry

`.boulder-cache/<config-stem>/<scenario_id>.h5` — one result each, reactor groups `r0…`, file-level
`payload_json`. Root attrs carry the entry's identity and display metadata: `store_version`,
`config_identity`, `fingerprint` (written **last**, as the validity signal), optional
`alt_fingerprints`, plus `label`, `order`, `computed_at` and any host KPI attrs (e.g. `t0_K`,
`final_temperature_K`). A plain single run is simply the N=1 entry, named `BASE` — or `BASELINE`
once the config declares `scenarios:`.

### Invariants

- `Y` is derived for the `solution` tier (exact for Cantera-consistent states).
- An unresolved/mismatched mechanism on read is a graceful cache miss (cache) or a clear error
  (scenario route) — never a crash.
- One `Solution` is cached per mechanism per process.

______________________________________________________________________

## 14. Inline run-set variations — `scenarios:` and `scenarios_sweep:`

A STONE file may declare multiple runs inline, instead of a glob of separate overlay files. Boulder
validates and passes these blocks through single-run normalization; `boulder.runset.iter_run_set` is
the **reference implementation** that turns them into the run set (one config per run) — eagerly for
`scenarios:` overlays and grid axes (`expand_scenarios`), one point at a time for a `for:`/`while:`
chain — and `python -m boulder.sweep_runner` is the generic runner that solves it into the
collection store. The GUI's Run Sweep uses the same iterator and the same single-run solve path, so
every point — grid, chain or overlay — is built from the YAML and solved identically. Hosts customize
naming/validation through hooks (`plugins.sweep_symbols`, `schema_entry`) rather than
re-implementing the semantics. The directives never alter the topology a single run sees — each
expanded run is the base with its overlay/patch deep-merged, and the directives stripped.

### `scenarios:` — a mapping of `id → overlay`

```yaml
scenarios:
  case_a:                    # key is the scenario id
    settings:
      solver: {atol: 1.0e-12}
  case_b:                    # a full STONE subtree, deep-merged onto the base
    stages:
      stage_2: {mechanism: h2o2.yaml}
    network:
      - {id: reactor1, IdealGasReactor: {initial: {temperature: 1400 K}}}
```

Each value is a STONE subtree (`metadata`/`stages`/`settings`/`network`/…) deep-merged onto the base
(id-keyed `nodes`/`connections` merge by id). The **key is the scenario id**. This is the same delta a
standalone `from:` overlay file carries — `from:` remains fully valid and is unaffected.

The unmodified base config is always part of the run-set too, as its own entry (id `BASELINE`,
listed first) — `scenarios:` only *adds* named variations, it never stands in for the base itself.
`BASELINE` is a reserved id: a `scenarios:` entry cannot use it.

### `scenarios_sweep:` — the run-set block

`scenarios_sweep:` holds **either** a Cartesian grid of axes **or** one sequential chain (`for:` /
`while:`), plus the optional host `runner:` (below). It may appear at the top level (expanded on the
base) **or inside a `scenarios:` entry** (expanded on that scenario only). Ids are suffixed
`__<label>=<value>`, the label being the axis name / the parameter's path leaf (or an explicit
`symbol:`).

#### Grid axes — independent points

```yaml
scenarios_sweep:
  T:  {path: "nodes[id=torch].properties.T_out", values: [2600, 2700]}
  mdot: {path: "...", min: 1.0e-4, max: 2.0e-4, num: 3}   # or min/max/num (+ spacing: log)
```

All axes are crossed as a Cartesian product, and every point is solved **independently** from the
network as written.

##### One axis, several targets

`path:` also accepts a **list**, so one swept value is written to every listed target:

```yaml
scenarios_sweep:
  inlet_temperature:
    path:
      - "network[id=fuel_air_mixture_tank].Reservoir.temperature"
      - "network[id=stirred_reactor].IdealGasMoleReactor.initial.temperature"
    values: [650, 700, 750]
```

Use this when the targets are the *same physical quantity* on different nodes — above, an inlet
reservoir's temperature and the initial state of the isothermal (`energy: "off"`) reactor it feeds.
They must move together: sweeping one alone is physically inconsistent, and giving them separate
axes would cross-multiply into mostly nonsense combinations. It stays **one** axis — three values
give three runs, not nine — and the scenario id is unchanged, labelled from the first path.

#### `for:` — a chain over a list of values

The Python `for T in [650, 700, ...]:` loop: the points are solved **in order**, and each may start
from the previous one.

```yaml
scenarios_sweep:
  for:
    parameter:                         # one path, or a list one value drives together
      - network[id=fuel_air_mixture_tank].Reservoir.temperature
      - network[id=stirred_reactor].IdealGasMoleReactor.initial.temperature
    values: [650, 700, 750, 775, 825, 850, 875, 925, 950, 1075, 1100]   # or min/max/num
    initial: from_previous             # each step starts from the previous step's converged state
```

#### `while:` — a chain that runs until a condition fails

The Python `while combustor.T > 500: sim.solve_steady(); tau *= 0.9` loop:

```yaml
scenarios_sweep:
  while:
    parameter: network[id=air_inlet].MassFlowController.tau_s
    condition: {path: "network[id=combustor].T", gt: 500}   # evaluated on the previous step's result
    update: {multiply: 0.9}                                # tau *= 0.9 after each step (or add: / set:)
    max_iters: 200                                         # safety cap
    initial: from_previous
```

(Quote a `network[id=…]` path inside a `{…}` flow mapping — `[` is a YAML flow indicator there; in
block style no quotes are needed.)

- The **first point is the config as written** and is always solved.
- Before every *later* point, `condition` is evaluated on the **previous step's result**: `path`
  names a reactor's `T`, `P`, `X.<species>` or `Y.<species>` (`network[id=<reactor>].T`), compared
  with exactly one of `gt` / `ge` / `lt` / `le`. Like a Python `while` re-testing after each
  iteration, the point that trips the condition has already been recorded (the extinguished
  combustor is in the store); the chain then ends.
- `update` — `multiply`, `add` or `set` — produces the next parameter value; `max_iters` caps the
  chain. Ids are `BASELINE__<label>=<value>` (`BASELINE__tau_s=0.09`), and the value is recorded
  under `metadata.sweep_point`, so the Sweep results plot gets its X axis like for a grid axis.
- A `while:` chain sizes as 0 in the availability report (`Run Sweep` shows no count): its length is
  only known once its condition trips.

#### `initial:` — where each chain step starts (`for:` and `while:`)

- `from_config` (the default): every step starts from the network as written — ordered, but
  otherwise the same as independent points.
- `from_previous`: a **warm start**. Every non-boundary reactor's converged temperature, pressure
  and composition become its `initial:` block for the next step — exactly what continuing an
  already-solved `ReactorNet` does. `Reservoir`s and `OutletSink`s are boundary conditions and are
  never touched; pressure is only seeded where the node has no top-level `pressure:` (a
  const-pressure reactor's operating constraint). The swept `parameter` is applied **after** the
  carry, so it always wins: an `energy: "off"` reactor swept in temperature keeps the prescribed
  temperature and carries only its composition. Step 0 has no previous step and starts from the
  config. Because the carried state lives *in* the merged config, it is part of the entry's
  fingerprint — incremental caching stays correct, and a cached (skipped) step still seeds the next
  one from the store.

A chain cannot share its block with grid axes, and a block holds at most one chain.

### `scenarios_sweep.runner:` — a host-produced run-set

When not even a chain can express the run-set, name a callable that produces it:

```yaml
scenarios_sweep:
  runner: "my_package.sweeps.custom:run"
```

The callable receives the resolved collection-store directory and writes the scenarios itself with
`boulder.scenario_store.write_entry` (which stamps the fingerprint, config identity and display attrs
the Scenario pane checks). It may declare optional `progress` — `(done, total, message)` —,
`config_path` and `stop_event` parameters:

```python
def run(store_dir, config_path=None, progress=None, stop_event=None): ...
```

`runner` is a reserved key inside the block: it is never interpreted as an axis, and may sit
alongside real axes. Boulder resolves and calls it **in-process**, like every other sweep. Prefer a
`for:`/`while:` chain whenever the points can be described in YAML: a runner bypasses the converter,
so the network it solves is not the one the file declares.

> **Note** — Boulder previously executed any file literally named `run_sweep.py` next to the config.
> That is gone: it tied behaviour to a filename, was invisible in the config, and broke silently.
> Declare the run-set in the config instead.

### Run-set semantics (union)

The run set is the **union**: the unmodified base (`BASELINE`, when `scenarios:` declares overlays)
**⊎** the top-level grid points *or* chain points **⊎** each `scenarios:` entry (each expanded across
its *own* inner block if present). A top-level grid and the scenarios do **not** cross-multiply. A
chain declared without `scenarios:` yields only its own points — its first point *is* the base
config, so no separate `BASELINE` entry is written.

### Legacy spellings

`sweep:` / `sweeps:` are accepted and renamed to `scenarios_sweep:` on load, with a warning naming
the replacement. `continuation:` (Section 10) is accepted and warned about; only the headless
`BoulderRunner.run_continuation` executes it — Run Sweep executes its `scenarios_sweep.while` form,
which is also what `sim2stone` emits for a detected `while reactor.T > N: solve_steady(); tau *= k`
loop.
