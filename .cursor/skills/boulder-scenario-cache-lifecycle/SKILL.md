______________________________________________________________________

## name: boulder-scenario-cache-lifecycle description: >- GUI test procedure for Boulder's scenario cache lifecycle: Clear Cache, Run Sweep, Run Simulation, and how the Scenario Pane's "Not computed yet" state and the network graph's node tint (grey/blue) each track (or don't track) those actions. Use when the user asks to verify scenario caching end-to-end, check Run Sweep vs. Run Simulation consistency, or the Clear Cache button's effect on the Scenario Pane and graph tint.

# Boulder scenario cache lifecycle (GUI test procedure)

Step-by-step procedure for verifying Boulder's scenario/sweep cache behaves
correctly through the GUI. Written against a config with a `scenarios:`
block, no host plugin required — pure Boulder built-in reactor kinds only.

## Example config

`configs/cstr_residence_time_scenarios.yaml` — the same CSTR as
`configs/default.yaml`, plus a `scenarios:` block with two named overlays
(`short_residence_time`, `long_residence_time`) that retune the inlet
`mass_flow_rate`. Solves in well under a second per scenario. If testing a
different config, it just needs a `scenarios:` mapping with 2+ entries.

## Procedure

```bash
conda activate boulder
cd frontend && npm run build && cd ..
boulder configs/cstr_residence_time_scenarios.yaml --no-open
```

1. **Open the config.** Confirm the header shows
   `cstr_residence_time_scenarios.yaml` (not `untitled.yaml`) and the
   Scenario Pane lists `BASELINE` + the two named scenarios, each
   "Not computed yet".

1. **Clear Cache, defensively.** The "Clear cache" button only appears
   once a sweep has produced a collection store — on a genuinely fresh
   config (no prior `*_scenarios.h5`), it's simply **absent**; that's
   correct, not a bug. Skip straight to step 3. If it *is* present (a
   store already exists from an earlier session), click it and confirm
   every row still reads "Not computed yet" afterward.

1. **Run Sweep.** Use the dropdown next to "Run Simulation" → "Run Sweep"
   → click the (now relabeled) primary button. Once it completes:

   - Every Scenario Pane row shows a timestamp ("just now"), not
     "Not computed yet".
   - The network graph's nodes turn blue (`rgb(59,130,246)` /
     Tailwind `blue-500`) — check via
     `window.__boulderCy.nodes().map(n => n.style('background-color'))`
     if canvas clicks aren't available to the agent.

1. **Run Sweep again, unchanged.** Re-run it with nothing edited. Every
   scenario — **including BASELINE** — must be skipped as a cache hit:
   `computed_at`/`fingerprint` (`GET /api/scenarios`) stay byte-identical
   to step 3, and the server console prints `cached, skipped` for all
   three. See "BASELINE re-solves every time" below if this fails —
   it's a real, previously-shipped bug with a one-line fix.

1. **Select BASELINE, then Run Simulation.** Click the BASELINE row, then
   the (relabeled) "Run Simulation" primary button. **Expect a real
   (fast) re-solve, not a cache hit** — confirm via network inspection
   that `POST /api/simulations/check-cache` returns `{"cached": false}`.
   This is not a bug: Run Sweep's collection store and Run Simulation's
   single-run result cache (`.boulder-cache/`) are separate stores in
   plain Boulder. A host can unify them by registering
   `plugins.on_scenario_solved` (see
   `boulder.cantera_converter.BoulderPlugins.on_scenario_solved`'s
   docstring) — without one, expect independent caches. The model solves
   fast enough that this can *look* like a cache hit; don't rely on
   wall-clock time as the check, use the network request.

1. **Clear Cache from the Scenario Pane.** Every row reverts to
   "Not computed yet". **The graph's nodes do *not* turn grey** if a
   result is still loaded/displayed (e.g. right after step 5) — that's
   deliberate (see `scenarioStore.ts::clearCache`'s comment: "the *base
   run's* result deliberately survives... so the graph's 'computed' node
   tint still correctly reflects the base simulation still loaded").
   Assert the Scenario Pane rows, not node color, for this step.

1. **Run Simulation for BASELINE again.** **Known limitation, not
   verified by this step as written:** the Scenario Pane's BASELINE row
   does **not** update after a plain Run Simulation — it stays
   "Not computed yet" indefinitely, because Run Simulation never writes
   into the sweep's collection store (the Scenario Pane's only data
   source). Only **Run Sweep** updates Scenario Pane rows. If you need
   BASELINE's row to reflect a fresh solve, use Run Sweep (step 3), not
   Run Simulation. (Tracked as a follow-up: unifying BASELINE's status
   across both actions needs a design decision, not a one-line fix.)

## Known issues found while writing this procedure

### BASELINE re-solves every time, even unchanged (fixed)

**Symptom:** step 4 shows `BASELINE` re-solving (a new `computed_at`/
`fingerprint`) on *every* Run Sweep, while named scenarios correctly
cache-hit. Only reproduces when the config's own collection store
(`<stem>_scenarios.h5`, written next to the config) lands **inside a git
working tree that also contains Boulder's own installed source** — e.g.
testing from Boulder's own `configs/` directory with an editable
(`pip install -e .`) install, exactly as this procedure does.

**Root cause:** Boulder's cache fingerprint includes a "source identity"
that hashes `git status --porcelain` + `git diff HEAD` for wherever the
`boulder` package is installed from (`result_cache._source_identity`) —
by design, so a code change busts the cache. The very first scenario ever
solved for a new config is fingerprinted *before* its own collection
store file exists on disk; every fingerprint computed afterward (store
file now present as an untracked change) reflects a different git-dirty
state. Whichever scenario solves first (always BASELINE) gets a
fingerprint that can never match again — a permanent, self-inflicted,
one-time cache-bust baked in by the very act of writing the store.

**Fix:** `*_scenarios.h5` is now in `.gitignore` (this file's own commit)
— the store never appears in `git status`, so it can never perturb its
own fingerprint. Reproduce the bug pre-fix by removing that `.gitignore`
line and re-running steps 3-4 from a clean git checkout.

### Native `confirm()` dialogs block headless/agent clicks

"Clear cache" and scenario deletion both guard on `window.confirm(...)`.
An agent driving the browser via `javascript_exec`/DOM `.click()` (no real
dialog to answer) gets a silent no-op — `window.confirm` returns `false`
by default with nothing to interact with, and the handler's
`if (!window.confirm(...)) return;` aborts before any network call.
**Stub it first:** `window.confirm = () => true;` before clicking, in the
same page context.

## Further reading

- [boulder-gui/SKILL.md](../boulder-gui/SKILL.md) — general GUI driving,
  canvas node selection, results tabs
- [boulder-scenario-editing/SKILL.md](../boulder-scenario-editing/SKILL.md)
  — editing a scenario's parameters via Properties panel / YAML pane
- `boulder/result_cache.py` — `compute_fingerprint`/`_source_identity`/
  `_git_dirty_token`
- `boulder/sweep_runner.py` — `prepare_scenario`, the shared
  normalize→resolve-mechanism→fingerprint pipeline both the GUI's
  in-process sweep and the CLI runner use
