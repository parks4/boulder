# Changelog

## 0.13.0 (unreleased)

One calculation path and one result store for every entry point. CLI run, CLI sweep, GUI run, GUI
sweep and the Python API all call `sweep_runner.run_set`; a single run is a run set of one entry.
Same config, same stored result. Closes #229, #230 and #231.

### Changed

- **One pipeline.** `sweep_runner.run_set` loads, expands, prepares (the runner's `normalize` and
  `validate`), fingerprints, checks the store, solves, stores and fires the hooks. The two sweep loops,
  the worker's store writer (`SimulationWorker._persist_to_cache`, `set_run_identity`) and the runner's
  headless store step are gone.
- **One loader.** `BoulderRunner.load` reads through `load_yaml_with_inheritance`: `from:` works on every
  path. Raw configs are plain containers, so the stored definition is dumped the same way everywhere.
- **One staged-solve driver.** `BoulderRunner.build()` delegates to `converter.build_network`; there is no
  second stage loop. It now applies `signals:` / `bindings:` like every other path. `solve_stage` and
  `build_viz_network` stay public for generated scripts and `run_continuation`.
- **One config, the server's.** `POST /api/simulations` and `POST /api/simulations/check-cache` take
  overlays and an entry id (`scenario_id`, `scenarios`, `simulation_time`, `time_step`, `force`), not a
  `config`: they expand the server's live resolved config. A canvas edit reaches it through
  `/api/configs/sync`, which the frontend calls before every run. The GUI's time overrides are written
  into `settings.solver` before expansion.
- **The stored run definition is the resolved config** (`from:` unfolded), and the YAML pane's Download
  serves it from the server (`POST /api/configs/resolved`). The user's file is never written unless they
  save.
- **One time-grid rule** (`sweep_runner.solver_window`). A transient (`advance_grid`) stage with no grid
  is an error; the hidden `end_time or 1 s` default is gone.
- `boulder --sweep --headless` runs in the calling process, so the runner class reaches it.
  `plugins.sweep_runner` still overrides it with a command run in its own process.

### Fixed

- Single runs fire `scenario_attrs` and `on_scenario_solved`, and store the same attributes as sweep
  entries (#229). A host that calls `run_contributors` from `on_scenario_solved` runs its contributors
  twice, as it already did on sweeps.
- The stored source of a `from:` config is the same on every path (#230).
- Headless `--run` records a real trajectory instead of a single point at t=0 (#231).

### Removed

- `BoulderRunner.run_headless(end_time, dt, persist)`: the keywords are gone. `run_headless` solves and
  writes the script; `--run` stores through `run_set`.
- `normalize_config_for_fingerprint` and `_resolve_run_grid` (`api/routes/simulations.py`).

### Upgrade notes

- **Fingerprints may change once.** Sweeps now prepare configs with the host runner's `normalize` and
  `validate` (as single runs did), configs with `from:` hash their resolved form, and runs with GUI time
  overrides hash the overridden `settings.solver`. Where those differ, an entry re-solves once. A host
  lists metadata it injects in `result_cache._RUN_LABEL_METADATA_KEYS` to keep its keys stable.
- Old entries stay readable: they only lack attributes the new path records.
