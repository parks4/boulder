# FMI / FMU Export — strategic direction

> **Status**: not implemented. This document describes the recommended approach
> for exposing Boulder reactor networks as FMUs (Functional Mock-up Units) so
> they can be embedded inside system-simulation tools like
> [Simulink](https://mathworks.com/products/simulink.html),
> [Dymola](https://www.3ds.com/products/catia/dymola),
> [OpenModelica](https://openmodelica.org), AVL Cruise, GT-SUITE, etc.

## Why this exists

Boulder's value is **Cantera-grade kinetics + declarative topology** (STONE).
Most control / system-simulation engineers do not run Cantera; they author
plant models in causal block-diagram tools. The
[FMI standard](https://fmi-standard.org) is the ISO-tracked interop format
those tools all consume. By exporting Boulder stages as FMUs we let the
chemistry users keep authoring in STONE while letting the control users wire
the reactor into their existing pipelines.

This is **Direction 1** in the
[`transient_driver_architectures`](.cursor/plans/transient_driver_architectures_e48e4f4f.plan.md)
strategic plan. It is recommended *after* Direction 2 (the in-STONE causal
layer of `signals: / bindings: / scopes:`) so the FMU export has well-defined
input/output boundaries to map from.

## What is FMI?

A `.fmu` file is a zip containing:

- `modelDescription.xml` — declares variables, units, default experiment.
- A C ABI shared library (`.dll` / `.so` / `.dylib`) that implements the
  FMI C API.
- Optional resources (Boulder would bundle the STONE YAML and the Cantera
  mechanism).

FMI has three released versions (1.0 / 2.0 / 3.0). We target **3.0**, which
adds proper unit metadata, clocks/events, and array variables. ([Spec](https://fmi-standard.org/docs/3.0.2/))

## Co-Simulation vs Model Exchange

| Mode | Who owns the integrator | Cantera fit |
|---|---|---|
| Model Exchange (ME) | The importer (e.g. Simulink) | Bad — would require re-exporting Cantera's RHS in C++ |
| Co-Simulation (CS) | The FMU itself (CVODES inside) | Native — Cantera already owns the integrator |

**Recommendation: Co-Simulation.** Each `doStep(t, dt)` call from the importer
forwards into `network.advance(t + dt)`.

## Architecture

```mermaid
flowchart LR
    YAML[STONE YAML] --> Conv[boulder converter]
    Conv --> Stage[Boulder stage = ReactorNet + bindings]
    Stage --> Wrap[FMI 3.0 CS wrapper]
    Wrap --> FMU[.fmu archive]
    FMU --> Tools["Simulink / Dymola / OpenModelica / fmpy / ..."]
```

Each Boulder **stage** becomes one FMU. A multi-stage STONE file produces a
bundle of FMUs that the importer co-simulates with its own master algorithm.
Cross-stage `connections` (handled today by `inter_stage_connections`)
become external FMU input/output signals at stage boundaries.

## Steady vs transient

FMI 3.0 Co-Simulation is inherently transient: the importer drives the FMU
forward in time via `doStep(t, dt)`. STONE's `solver.mode: steady`
configurations therefore export with a slightly different convention:

| `solver.mode` | FMU behaviour |
|---------------|-------------------------------------------------------------------------------|
| `transient` | `doStep` calls `network.advance(t + dt)` directly |
| `steady` | the FMU exposes a `solve_steady_now` boolean input; flipping it to true triggers `solve_steady()` and the next `doStep` returns the converged state |

This keeps the export honest: a steady-state model loaded into Simulink is
not pretending to be a 10-line ODE.

## Variable mapping

The Direction 2 causal layer maps directly to FMI variable kinds:

| STONE concept | FMI 3.0 kind | Example |
|-------------------------------------|----------------|---------------------------------------------------|
| `signals: <id>` exposed externally | `input` | `inlet_mdot` (kg/s) |
| Bound to `connections.<id>.mdot` | `input` | `connections.inlet_mfc.mass_flow_rate` |
| Bound to `nodes.<id>.E_reduced` | `input` | `nodes.r1.reduced_electric_field` |
| `scopes: <variable>` | `output` | `nodes.combustor.T` |
| Continuation parameter | `parameter` | `tau_s` |
| `phases.gas.mechanism` | `parameter` | `mechanism` (string, fixed at instantiation) |
| Solver `rtol`/`atol` | `parameter` | `tolerance.rtol`, `tolerance.atol` |

Units come from STONE's existing unit handling
([`boulder/utils.coerce_unit_string`](boulder/utils.py)) and are written to
`modelDescription.xml` in the FMI 3.0 unit-definition format.

## Implementation paths

### Path A — Python-hosted FMU (recommended start)

Use [`pythonfmu3`](https://github.com/NTNU-IHB/PythonFMU3) to package
`BoulderRunner` as an FMU. Skeleton:

```python
from pythonfmu3 import Fmi3Slave, Real, String, Causality, Variability

class BoulderFMU(Fmi3Slave):
    author = "Boulder"
    description = "Cantera reactor network from STONE YAML"

    config_path: str
    rtol: float = 1e-6
    atol: float = 1e-8

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from boulder.runner import BoulderRunner
        self.runner = BoulderRunner.from_yaml(self.config_path)
        self.plan = self.runner.build_stage_graph()
        self._t = 0.0
        for sig_id in self.runner.exposed_inputs:
            self.register_variable(Real(sig_id, causality=Causality.input))
        for scope_var in self.runner.scopes:
            self.register_variable(Real(scope_var, causality=Causality.output))

    def do_step(self, current_time, step_size):
        for sig_id, val in self._pending_inputs.items():
            self.runner.set_input(sig_id, val)
        self.runner.advance(current_time + step_size)
        self._t = current_time + step_size
        return True
```

Pros: ships in ~2 weeks; full Cantera available via the embedded interpreter.

Cons: the resulting FMU requires either (a) the importer to provide a Python
runtime with Boulder installed, or (b) shipping a self-contained interpreter
(`pythonfmu3` does this for you, but the `.fmu` grows to ~150 MB once Cantera

- NumPy + SciPy + Boulder + ruamel.yaml are bundled).

### Path B — Native C++ FMU (long-term)

A thin C++ wrapper that links `libcantera` and implements FMI 3.0 directly.
~5 KB FMU, no Python dependency.

Pros: self-contained, fast to load, suitable for embedded/HIL targets.

Cons: significant build/CI lift (per-platform binary wheels, cross-compile to
the importer's platform). Defer until a paying user requests it.

### Path C — FMI Co-Sim via [`fmpy`](https://github.com/CATIA-Systems/FMPy) for *consuming* third-party FMUs inside Boulder

The reverse direction: let Boulder import an external FMU as one of its
nodes (e.g. an electrochemistry FMU shipped by a partner). Out of scope for
this document; would be a separate `boulder/plugins/fmu_node.py`.

## Worked example: `combustor.py` as an FMU

After Direction 2 ships, `combustor.yaml` would contain:

```yaml
signals:
  - id: tau
    Constant: { value: 0.1 }
bindings:
  - { source: tau, target: connections.inlet_mfc.tau_s }
scopes:
  - { variable: nodes.combustor.T,                  output: true }
  - { variable: nodes.combustor.heat_release_rate,  output: true }
```

Built with:

```bash
boulder export-fmu combustor.yaml --out combustor.fmu --fmi-version 3.0
```

Used from Python:

```python
import fmpy
result = fmpy.simulate_fmu(
    "combustor.fmu",
    start_time=0.0, stop_time=1.0, output_interval=0.01,
    start_values={"tau": 0.1},
    input={"tau": lambda t: 0.1 * 0.9 ** int(t * 10)},   # the residence-time sweep
    output=["nodes.combustor.T", "nodes.combustor.heat_release_rate"],
)
```

Or in Simulink: drag the `.fmu` onto the canvas, connect a `From Workspace`
block to the `tau` input and a `Scope` to the `T` output.

## Roadmap

| Step | Effort | Depends on |
|------|--------|------------|
| 1. Direction 2 lands (signals/bindings/scopes in STONE) | (separate plan) | — |
| 2. `boulder export-fmu` CLI command using `pythonfmu3` | ~1 week | step 1 |
| 3. FMI 3.0 unit metadata wiring | ~2 days | step 2 |
| 4. CI test: round-trip via `fmpy.simulate_fmu` against the YAML solve | ~3 days | step 2 |
| 5. CI test: import the FMU in OpenModelica via OMSimulator | ~2 days | step 4 |
| 6. Native C++ path (Path B above) | ~3-4 weeks | only on demand |

Total to a usable Python-hosted FMU export: **roughly 2 weeks** once the
causal layer is in place.

## What this is not

- **Not a replacement for Simulink.** Boulder will never compete with mature
  causal block-diagram tools. The point is interop, not feature parity.
- **Not Modelica.** Modelica is acausal/equation-based; FMI is the *export*
  format used by those tools. We export FMUs; we do not write Modelica.
- **Not a substitute for the in-STONE causal layer.** Direction 2 is needed
  internally even if FMU export is never built — it is what gives transient
  Cantera examples a clean home in YAML.

## References

- [FMI 3.0 Specification](https://fmi-standard.org/docs/3.0.2/)
- [Modelica Association — FMI Standard](https://modelica.org/projects/)
- [`pythonfmu3` — Python → FMU 3.0 generator](https://github.com/NTNU-IHB/PythonFMU3)
- [`fmpy` — Python FMU simulator/validator](https://github.com/CATIA-Systems/FMPy)
- [OpenModelica `OMSimulator`](https://openmodelica.org/doc/OpenModelicaUsersGuide/latest/omsimulator.html)
- Cantera Python API: <https://cantera.org/stable/python/index.html>
