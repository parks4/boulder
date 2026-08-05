______________________________________________________________________

## name: boulder-scenario-cache-lifecycle description: >- GUI test procedure for Boulder's result-store lifecycle: Clear Cache, Run Sweep, Run Simulation, and how the Scenario Pane's "Not computed yet" state and the network graph's node tint (grey/blue) each track (or don't track) those actions. Use when the user asks to verify scenario caching end-to-end, check Run Sweep vs. Run Simulation consistency, or the Clear Cache button's effect on the Scenario Pane and graph tint.

# Boulder result-store lifecycle (GUI test procedure)

Step-by-step procedure for verifying Boulder's result store behaves
correctly through the GUI. Written against a config with a `scenarios:`
block, no host plugin required — pure Boulder built-in reactor kinds only.

## One store, one lookup

There is a **single** result store. Every solve lands in it — a whole
sweep or a single run — because `runset.expand_scenarios` always yields at
least one entry, so "single-shot" and "sweep" are the same code path at
N=1 and N=3:

```
<config_dir>/.boulder-cache/<stem>/
    BASE.h5 | BASELINE.h5 | <scenario_id>.h5     # one file per entry
    artifacts/<scenario_id>/...
```

The **name** is the key; the `fingerprint` attr recorded under that name is
the staleness check. Two consequences this procedure exists to verify:

- Run Simulation and Run Sweep **see each other's work**. Solving BASELINE
  either way produces one entry, and the other action reuses it.
- An entry holds **one** result, the latest. Re-running an unchanged entry
  is a hit; going *back* to a previous value re-solves. Keeping a value
  around is what authoring a scenario is for.

Two scopes clear it: the pane header's eraser
(`POST /api/scenarios/clear-cache`, `button[title^="Clear cache"]`) removes
the whole store directory, and a row's own eraser
(`POST /api/scenarios/<id>/clear-cache`,
`button[title^="Clear this scenario"]`) drops that one entry so the next
Run Sweep re-solves it alone. Neither touches a scenario's definition.

Historically these were two separate stores (a content-addressed
`.boulder-cache/<fingerprint>/` for single runs, a name-addressed
`<stem>_scenarios.h5` for run-sets) which disagreed permanently about
BASELINE. If you are reading an older description of steps 5/7 expecting a
cache *miss* and a never-updating pane row, that is the behaviour that was
removed.

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
   once the store has entries — on a genuinely fresh config it is simply
   **absent**; that's correct, not a bug. Skip to step 3. If present,
   click it and confirm every row still reads "Not computed yet".
   It is an **icon button** (eraser) with no text: find it by
   `button[title^="Clear cache"]`, not by text content.

1. **Run Sweep.** Use the dropdown next to "Run Simulation" → "Run Sweep"
   → click the (now relabeled) primary button. Once it completes:

   - Every Scenario Pane row shows a timestamp ("just now"), not
     "Not computed yet".
   - The network graph's nodes turn blue (`rgb(59,130,246)` /
     Tailwind `blue-500`) — check via
     `window.__boulderCy.nodes().map(n => n.style('background-color'))`
     if canvas clicks aren't available to the agent.

1. **Run Sweep again, unchanged.** Every scenario — **including
   BASELINE** — must be skipped as a cache hit: `computed_at`/
   `fingerprint` (`GET /api/scenarios`) stay byte-identical to step 3, and
   the server console prints `cached, skipped` for all three.

1. **Select BASELINE, then Run Simulation.** Click the BASELINE row, then
   switch the dropdown back to "Run Simulation" and click. **Expect a
   cache HIT**: `POST /api/simulations/check-cache` returns
   `{"cached": true}`, the server logs `Cache HIT (fingerprint …)`, and
   `computed_at` is unchanged from step 3. This is the single store doing
   its job — Run Simulation reuses the sweep's solve.

1. **Clear Cache from the Scenario Pane.** In that one click: every row
   reverts to "Not computed yet", `GET /api/scenarios` reports zero entries,
   the results area empties, and the graph's nodes go **grey**.

   It is an **icon button with no text** — find it by
   `button[title^="Clear cache"]`, not by text content.

   Older notes here said the nodes deliberately stay blue, because clearing
   removed only *scenario* results while the base run survived in a second,
   separate cache. With one store, `clear-cache` removes the whole directory
   including the base entry, so a still-tinted graph would be backed by
   nothing.

1. **Run Simulation again.** The **BASELINE row updates to "just now"**
   within a couple of seconds, and `GET /api/scenarios` shows exactly one
   entry, `BASELINE`. The other two stay "Not computed yet" — correct, they
   were not solved.

   Two things are being checked here at once: that a plain run writes the
   store under the *same name* a sweep uses, and that the pane re-fetches
   on completion.

## Known issues found while running this procedure

### A plain run stored the base under a second name (fixed)

**Symptom:** step 7 grows a phantom `BASE` row while the authored
`BASELINE` row still reads "Not computed yet" — one result, two names.

**Root cause:** `expand_scenarios` names the base entry `BASELINE` once a
config declares `scenarios:`, but a plain Run Simulation hard-defaulted to
`BASE`. The raw config never reached the worker on that path (it arrived
only via `set_run_identity`, which a single run never called), so the
worker could not know either the base's name *or* a declared
`metadata.extra.cache_store` location.

**Fix:** `runset.base_entry_id` is the one place the naming rule lives, and
`POST /api/simulations` always hands the worker the raw config.

### Clear Cache left the graph blue (fixed)

`clearCache` kept the displayed results on purpose, justified by the base run
surviving in the *other* cache. Unifying the stores deleted that other cache
without anyone re-reading the justification, so the graph stayed "computed"
while nothing was stored. It now clears the results in the same click.

### The pane did not refresh after a single run (fixed)

A sweep refreshes the scenario list on completion; a plain run did not, so
even a correctly stored BASELINE stayed "Not computed yet" on screen.
`SimulateCard` now refreshes when results arrive.

### Cache never hits while editing Boulder itself (by design)

The fingerprint folds in a "source identity" that hashes
`git status --porcelain` + `git diff HEAD` for wherever the `boulder`
package is installed from (`result_cache._source_identity`), so a code
change busts the cache. **Committing between two steps of this procedure
will make step 4 or 5 re-solve** — that is the mechanism working, not a
failure. Keep the worktree untouched for the duration of a run, or set
`BOULDER_CACHE_IGNORE_CODE=1`.

An earlier variant of this bit harder: the store used to be written *next
to the config*, so the store file itself appeared in `git status` and
perturbed its own fingerprint — a permanent self-inflicted cache-bust for
whichever scenario solved first. Living under `.boulder-cache/` removes
that by construction.

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
- `boulder/scenario_store.py` — the store: layout, identity guard, and why
  `fingerprint` is written last
- `boulder/result_cache.py` — identity only now:
  `compute_fingerprint`/`_source_identity`/`_git_dirty_token`
- `boulder/sweep_runner.py` — `prepare_scenario`, the shared
  normalize→resolve-mechanism→fingerprint pipeline both the GUI's
  in-process sweep and the CLI runner use
