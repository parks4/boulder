______________________________________________________________________

## name: boulder-scenario-editing description: >- Verify scenario-parameter editing in the Boulder GUI (Properties panel and the scenario overlay YAML pane) via interactive browser automation. Use when the user asks to test/verify editing a scenario's node or connection properties, check that GUI edits land in the right scenario overlay (not the base network), or exercise edge cases around BASELINE, cross-node validation conflicts, and GUI/YAML live sync. Requires boulder >= the commit making scenario authoring in-memory-only (see `boulder/scenario_editor.py`'s module docstring) and Run Sweep in-process (see `boulder/api/routes/sweep.py`).

# Boulder scenario editing (GUI + YAML)

Guide for agents verifying that editing a scenario's parameters — through the
structured Properties panel *or* the scenario's raw YAML pane — behaves
correctly, stays in sync between the two, and fails loudly (not silently)
when it should.

## Mental model — read this first

**Nothing about scenario authoring touches disk.** Creating, editing,
renaming, or deleting a scenario overlay only mutates this browser session's
own in-memory state (`scenarioStore.overlays` — a `{scenario_id: overlay}`
map, seeded once from the config's `scenarios:` block when the page loads and
never re-read from disk after). The backend (`boulder/scenario_editor.py`,
`boulder/api/routes/scenarios.py`) is a pure calculator: every scenario route
takes the caller's *current* overlays map in the request body and returns the
*new* one — same "validate/compute, never persist" pattern the main config
YAML pane already used (`/configs/parse`). The one way to get a scenario onto
disk is the Scenario YAML pane's **"Download full YAML"** button, which
renders the base config deep-merged with that one scenario's overlay and
downloads it as a file — the user decides what to do with it from there.

Two independent things can be "active" in the left Network card / Properties
panel, and edits go to different places depending on which:

| Active selection | "Edit YAML" button | Where a Properties-panel Save lands |
|---|---|---|
| No scenario / **BASELINE** | Plain `Edit YAML` — full base config | The base network (`updateNode`/`updateConnection`, local + deferred to next sync — also never touches disk for a real preloaded file) |
| A real scenario (e.g. `C1T`) | `Edit YAML (<scenario>)` — scoped overlay | That scenario's overlay only, in `scenarioStore.overlays` (in-memory) |

STONE v2 is authored **per-stage** (or one flat `network:` list) with
type-keyed properties — never a generic `nodes:`/`properties:` shape:

```yaml
torch_stage:
- id: torch
  PlasmaTorchInstantaneousHeating:
    electric_power_kW: 120
```

A scenario overlay mirrors this shape but only lists the fields that
actually differ from the base — `scenario_editor._entity_location` finds
which stage list and type key an entity uses from the base config, so the
API only ever needs the entity id, never the stage/kind.

**Run Sweep runs in-process now** (no subprocess, no `run_sweep.py`): the
frontend POSTs its current base config's startup snapshot plus
`scenarioStore.overlays` to `POST /api/sweep/run`, and the backend solves each
expanded scenario through the exact same `SimulationWorker` a plain "Run
Simulation" uses — one scenario after another, in a background thread. This
means Run Sweep always sees this session's live, unsaved scenario edits, with
no "did I save first?" step.

## Prerequisites

```bash
conda activate bloc   # or whichever env has an editable `boulder` install
cd boulder/frontend && npm run build
bloc path/to/config.yaml --no-open --port 8050 --no-port-search
```

The config needs at least one authored scenario. If none exists yet, create
one from the GUI (see step 2 below) instead of hand-editing YAML.

## Standard verification workflow (browser)

Copy and track:

```
Scenario editing check:
- [ ] Scenarios pane visible (not collapsed) and a non-BASELINE scenario exists
- [ ] Selecting it relabels the button "Edit YAML (<id>)"
- [ ] GUI edit → Properties panel shows new value in amber, tooltip "Baseline value: <old>"
- [ ] Base (BASELINE) value is unchanged after the scenario edit
- [ ] Re-opening Edit on that field now shows the *override*, not the base value
- [ ] The on-disk config file is byte-for-byte unchanged after the edit
- [ ] Open the scenario's YAML pane → GUI edit appears there live, no reopen needed
- [ ] Edit the YAML pane directly → Properties panel updates live, no reselect needed
- [ ] "Download full YAML" produces a file with the base config merged with the edit
- [ ] BASELINE: no working delete button; its pencil opens the full YAML pane
- [ ] Run Sweep picks up the unsaved edit without any extra save step
```

1. Navigate to `http://127.0.0.1:8050/`.
1. If the Scenarios pane is missing, it's likely collapsed from a previous
   session (persisted in `localStorage['boulder-layout'].rightCollapsed`) —
   click the "Collapse/Expand right sidebar" header button, or clear that
   key and reload.
1. Select a scenario (see the DOM-id trick below — the row title is the
   scenario id, i.e. its `scenarios:` key; `metadata.description` is only a
   subtitle).
1. Select a node or connection on the graph (canvas — see the Cytoscape trick
   below, it's far more reliable than pixel-coordinate clicks for this).
1. Click **Edit**. The field shown is the scenario's *currently effective*
   value — the override if one already exists, otherwise the base value.
1. Change the value, click **Save**.
1. Assert: the field re-renders in amber (`text-amber-600`/`text-amber-400`)
   with `title="Baseline value: <old>"`; a toast reads
   `Scenario "<id>" overlay updated`.
1. Confirm the on-disk YAML file's mtime/content is unchanged (e.g. `git diff`
   on a scratch config, or hash the file before/after) — the edit only exists
   in this browser session.
1. Click **Edit YAML (`<id>`)** (or the scenario row's pencil) to open the
   scoped pane and confirm the overlay text matches what was just saved.
1. Click **Download full YAML** in that pane; confirm the downloaded file
   contains both the base network and the edited field, merged.

### Reliable interactive-browser techniques

Canvas clicks and label-text matching are fragile for this feature
specifically (Cytoscape renders to `<canvas>`; scenario labels are often
non-unique). Prefer:

```js
// Select a scenario by id (ScenarioPane assigns this id to every row button)
document.getElementById('scenario-C1T').click();

// Select a node/connection on the graph without pixel coordinates
window.__boulderCy.getElementById('torch').emit('tap');

// Read/write the scenario YAML pane's Monaco content directly
window.monaco.editor.getModels()[0].getValue();
window.monaco.editor.getModels()[0].setValue('torch_stage:\n- id: torch\n  ...\n');
```

`window.__boulderCy` is a debug handle exposing the live Cytoscape instance;
`window.monaco` is the global Monaco namespace once the lazy editor chunk has
loaded (poll for it, or wait ~1s after opening a YAML pane).

Capture toasts to confirm feedback, not just DOM state — several fixes in
this area are specifically about *toasting the right thing* rather than
silently no-oping:

```js
Array.from(document.querySelectorAll('[data-sonner-toast]')).map(t => t.textContent)
```

## Edge cases to check

| Case | Expected behavior | Why it matters |
|---|---|---|
| **No-op save**: open Edit (shows the current effective value), click Save without changing anything | Toast `No changes to save`. No API call. | Previously silent — looked identical to a successful save with zero feedback. |
| **Re-editing an already-overridden field**: open Edit on a field that already has an override | Shows the *override*, not the base value — editing seeds from `previewDisplayProperties` (base ⊕ active scenario overlay), not the base alone. | The GUI must never show a stale/wrong starting point for an edit. |
| **Cross-node validation conflict**: e.g. set `pressure` on an `OutletSink`/boundary node when the model requires it declared on exactly one node | The edit still applies to this session's in-memory overlay, but the follow-up preview refresh fails; toast reads `Scenario "<id>" overlay saved, but it no longer previews cleanly: <STONE v2 error detail>`. | `loadPreview` catches its own error into `previewError` rather than rejecting; that field must be checked explicitly or the failure is silent. |
| **Edit while calculating**: try to save a scenario-overlay edit while Run Sweep / Run Simulation is active | Blocked immediately: toast `Wait for the current calculation to finish before editing a scenario.` No API call. | A running sweep already captured its own overlay snapshot when it started, so this can't race it — but its in-flight results still reflect the pre-edit values, which would be confusing. |
| **GUI edit while the scenario's YAML pane is already open** | The open pane's Monaco content updates to include the new override, without closing/reopening. | Was fetched once on open; now also refetches on `scenarioStore.revision` bump. |
| **YAML-pane edit while the Properties panel has the same node selected** | Properties panel re-renders with the new value immediately. | Was only refreshing the scenario list, not `previewNodes`/`previewConnections`. |
| **Unsaved YAML-pane edit + an unrelated scenario write elsewhere** | The pane's unsaved text is **not** clobbered — the dirty-guard (`value !== baseline`) skips the auto-refetch. | Mirrors `YamlPane`'s existing guard for the base config; verify by typing in the pane, then triggering a save from the Properties panel for the same scenario, and confirming the typed (unsaved) text survives. |
| **Kind-less logical connection** (`source`+`target`, no type key, e.g. an inter-stage handoff) | Edited properties land directly on the item (`{id, source, target, logical: true}`), not nested under a type key. | Only ~half of connections have a type key; the other half are pure topology edges. |
| **Connection edit** (e.g. a `MassFlowController`'s `mass_flow_rate`) | Same overlay path as nodes. | Verify this isn't a nodes-only code path — `isNode` branches at the call site, not inside the API. |
| **First-ever override on an empty overlay** (`scenarios: {<id>: {}}`) | Creates the stage-list key and entry from scratch. | The common case for a freshly authored scenario. |
| **Re-editing an already-overridden entity** (a second field on the same node) | Merges into the *same* entry — does not duplicate the entity or wipe the first override. | `update_scenario_entity` finds-or-creates the entry by id before merging properties. |
| **BASELINE**: delete button | A disabled `Ban` icon in the same slot (not hidden — hiding it misaligned the row against others), tooltip explains why. | BASELINE is the base config's own unmodified run, not an authored overlay — nothing to delete. |
| **BASELINE**: edit | Pencil / "Edit YAML" opens the **full** base YAML pane, not the scoped overlay editor. | |
| **Run Sweep after unsaved edits** | The sweep sees every scenario's *current* in-memory overlay, including edits never explicitly "saved to disk" (there's no such action) — no extra step needed before Run Sweep. | Confirms the frontend sends `scenarioStore.overlays` in the sweep request body, not something the backend re-reads from a file. |
| **Page reload after editing a scenario** | Every in-memory edit is gone — the page reseeds `scenarioStore.overlays` from the config's on-disk `scenarios:` block, which was never touched. | This is the intended tradeoff: "Download full YAML" is the explicit save step; a reload is not a silent-loss bug. |

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| "Editing doesn't seem to register" — value never changes | A **prior** edit already broke this scenario's preview (see cross-node conflict above) and every subsequent `loadPreview` 422s | Check for an error toast on save; the browser Network tab's `POST .../scenarios/{id}/preview` response body has the detail; fix or clear the offending field via the scenario's YAML pane |
| "Edit YAML" button doesn't say `(scenario)` | No scenario is actually active, or BASELINE is | Confirm via `document.getElementById('scenario-<id>')`'s classes, or just re-click the row |
| Scenarios pane not visible at all | Right sidebar collapsed (persisted) | Click the sidebar toggle, or `localStorage.setItem('boulder-layout', JSON.stringify({...JSON.parse(localStorage.getItem('boulder-layout')), rightCollapsed: false}))` then reload |
| YAML pane / Properties panel stays stale after a save elsewhere | Frontend build predates the revision-triggered refetch fix | `npm run build`; hard-reload; confirm the served JS bundle hash changed |
| A scenario edit "disappeared" | Page was reloaded — see the edge case above; this is expected, not a bug | Re-apply the edit, or use "Download full YAML" before reloading next time |
| `PATCH .../entities/{id}` → 405 or unexpected response shape | Backend route source changed but the **Python server process** wasn't restarted (unlike frontend static assets, route registration only happens at process startup) | Kill and restart the `bloc`/`boulder` process |

## Further reading

- [boulder-gui/SKILL.md](../boulder-gui/SKILL.md) — general server startup, canvas selection, results tabs
- `boulder/scenario_editor.py` — pure overlay transforms (`create_scenario`, `update_scenario_entity`, `_entity_location`, `render_full_yaml`)
- `boulder/api/routes/scenarios.py` — the stateless scenario routes
- `boulder/api/routes/sweep.py` — Run Sweep's in-process loop over `SimulationWorker`
- `frontend/src/stores/scenarioStore.ts` — `overlays`, the session's source of truth
- `frontend/src/components/panels/PropertiesPanel.tsx` — scenario-aware `handleSave`
- `frontend/src/components/panels/ScenarioYamlPane.tsx` — the docked overlay editor + "Download full YAML"
