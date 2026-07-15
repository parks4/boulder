# FlowReactor / FlowReactorSurface Support — Design Sketch (Deferred)

> **Status:** design only, not scheduled. Implementation is explicitly deferred pending
> a separate scoping decision — do not start Task 1 without re-confirming priority.

**Goal:** Support Cantera's `ct.FlowReactor` (plug-flow, distance-marched) and
`ct.FlowReactorSurface` (coupled spatial surface-coverage evolution) so examples like
`surf_pfr.py` / `surf_pfr_chain.py` / `1D_pfr_surfchem.py` can be modeled in Boulder
instead of being marked `status: unsupported` in `boulder_examples/examples/manifest.yaml`.

**Repo:** Boulder (`boulder/boulder/cantera_converter.py`, `boulder/boulder/sim2stone.py`,
`boulder/boulder/config.py`, `frontend/src/components/results/PlotsTab.tsx`)

______________________________________________________________________

## Background

### Why this doesn't fit today's model

Every reactor type Boulder currently supports (`IdealGasReactor`, `ConstPressureReactor`,
`IdealGasMoleReactor`, etc.) is a 0-D control volume advanced through **time** as part of a
`ct.ReactorNet`. The entire STONE schema, `cantera_converter.py`'s `create_reactor_from_node`
(~line 950), and the frontend's plotting assumptions (`PlotsTab.tsx`, always keyed on `t`)
are built around that.

`ct.FlowReactor` is fundamentally different:

- It represents a plug-flow duct and is integrated along **distance**, not time
  (`reactor.distance`, driven by `mass_flow_rate` and cross-sectional `area`).
- `ct.FlowReactorSurface` attaches wall surface chemistry to that duct — site coverages
  evolve as a function of the same distance march, coupled back into the gas phase.

There is currently no "independent variable" concept in STONE at all (time is implicit
everywhere), no surface-phase node kind, and no distance-based plotting support.

### Current state (confirmed by investigation, 2026-07-14)

- `create_reactor_from_node` has a plain `if/elif` chain over reactor type strings
  (`IdealGasReactor`, `ConstPressureReactor`, `IdealGasConstPressureReactor`,
  `IdealGasConstPressureMoleReactor`, `IdealGasMoleReactor`, `Reservoir`, legacy
  `OutletSink`), plus a plugin registry (`self.plugins.reactor_builders`) checked first.
  `FlowReactor` is entirely absent — not stubbed, not partially wired.
- `build_connection` only knows `MassFlowController`, `Valve`, `PressureController`,
  `Wall` — no `ReactorSurface`/`FlowReactorSurface` handling anywhere.
- `sim2stone_ast.py` / `sim2stone_trace.py` have zero references to `FlowReactor`.
- `boulder_examples/examples/manifest.yaml` already documents the gap accurately:
  `1D_pfr_surfchem`, `surf_pfr`, `surf_pfr_chain` are all `status: unsupported` with
  reasons naming `FlowReactor`/`FlowReactorSurface` directly.

### Success criteria (for whenever this is picked up)

1. A YAML node of `type: FlowReactor` builds a working `ct.FlowReactor` with
   `mass_flow_rate`, `area`, initial `T`/`P`/`X`.
1. A YAML node of `type: FlowReactorSurface` (or a `surface:` property on the
   `FlowReactor` node) attaches surface chemistry with initial coverages and a surface
   mechanism reference.
1. sim2stone can convert a hand-written `ct.FlowReactor` + `ct.FlowReactorSurface`
   Cantera script back into STONE YAML (reverse direction), following the existing
   AST-detection pattern used for Gaussian MFC schedules.
1. The frontend plots these nodes' output against `distance`, not `t` — a per-node
   x-axis override, not a global change.
1. `surf_pfr.py` runs end-to-end as a new boulder_examples catalog entry, replacing its
   `status: unsupported` manifest entry.
1. New tests cover both directions (YAML→Cantera and Cantera→YAML).

______________________________________________________________________

## Proposed shape

### Task 1 — STONE schema: distance axis

**Files:** `boulder/boulder/config.py`, `boulder/docs/stone.rst`

Add an explicit `axis: distance` marker (parallel to today's implicit `axis: time`) at
the node or stage level, plus a `distance_end` / grid config — mirroring how
`advance_grid`/`micro_step` solver hints already carry timing params in
`sim2stone_ast.py`, but for a distance grid instead of a time grid.

### Task 2 — `FlowReactor` node construction

**Files:** `boulder/boulder/cantera_converter.py` (`create_reactor_from_node`)

New branch alongside the existing reactor-type chain: construct `ct.FlowReactor`,
set `mass_flow_rate`, `area` (constant or profile), initial thermodynamic state.
Follow the existing per-branch style (see the `Reservoir` branch for the simplest
template).

### Task 3 — `FlowReactorSurface` construction + attachment

**Files:** `boulder/boulder/cantera_converter.py` (new builder, or extend
`build_connection`)

New node kind or connection kind that attaches a `ct.FlowReactorSurface` to a
`FlowReactor` node: `site_density`, initial coverages, surface mechanism file.
Needs a decision: separate node (cleaner, matches "surface phase as its own thing")
vs. a property bag on the `FlowReactor` node (less STONE surface area, less flexible).
Recommend separate node + new connection kind, consistent with how `Wall` is already
a first-class connection rather than a property of the reactors it joins.

### Task 4 — sim2stone reverse-direction support

**Files:** `boulder/boulder/sim2stone.py`, `boulder/boulder/sim2stone_ast.py`

Detect `ct.FlowReactor`/`ct.FlowReactorSurface` instances during export; emit the
`axis: distance` marker instead of assuming time; export distance-grid timing the same
way `_detect_advance_timing` extracts time-grid params today.

### Task 5 — Frontend distance-axis plotting

**Files:** `frontend/src/components/results/PlotsTab.tsx`

`PlotsTab.tsx` currently assumes every series is keyed on `t`. Add a per-node override
(read from the node's `axis` property, set by Task 1) so a `FlowReactor` node's series
plot against `distance` on the x-axis instead.

### Task 6 — Tests + example

**Files:** new `tests/test_sim2stone/test_flow_reactor.py`,
`boulder_examples/adapters/surf_pfr.py`, `boulder_examples/examples/surf_pfr.yaml`,
update `boulder_examples/examples/manifest.yaml` (`surf_pfr` entry:
`status: unsupported` → `status: adapted`).

______________________________________________________________________

## Rough scope estimate

Schema + converter + sim2stone + frontend x-axis + tests + example ≈ **3–7 days** of
focused work. This is closer to "add a new reactor family" than "add one enum value" —
treat it as its own PR/milestone, not a quick side-diff.

## Agent constraints (for whoever picks this up)

| Do | Don't |
|----|-------|
| Confirm scope/priority before starting Task 1 | Assume this doc means the work is scheduled |
| Follow the existing per-reactor-type branch style in `create_reactor_from_node` | Invent a parallel reactor-construction pathway |
| Reuse the AST-signal-detection pattern already used for Gaussian MFC schedules | Add live-Func1-object introspection (known to not work — see `mass_flow_rate`/`wall.velocity`) |
| Keep `axis: distance` opt-in / per-node | Change the default x-axis for existing time-integrated reactors |
| Run the full test suite + `surf_pfr` example before claiming done | Skip `FlowReactorSurface` silently while claiming full support |
