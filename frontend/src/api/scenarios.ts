import { apiFetch } from "./client";
import type { SimulationResults } from "@/types/simulation";

/** One precomputed scenario (trajectory) in the active store. */
export interface ScenarioMeta {
  id: string;
  t0_K: number;
  label: string;
  reactor_mode?: string;
  n_points?: number;
  final_temperature_K?: number;
  solid_carbon_yield_pct?: number;
  /** Unix seconds when this scenario was computed (per-scenario; newer stores). */
  computed_at?: number;
  /** Extra numeric KPI attrs a sweep runner may attach (e.g. "final_X_CO"). */
  [key: string]: unknown;
}

export interface ScenarioListResponse {
  available: boolean;
  store?: string;
  mechanism?: string | null;
  reactor_mode?: string | null;
  /** Unix seconds when the store (sweep) was written (fallback for all rows). */
  created_at?: number | null;
  scenarios: ScenarioMeta[];
  /**
   * Every scenario id in the config's `scenario:` mapping, regardless of
   * whether a sweep has computed it yet — the source of truth for what can
   * be used as an Add Scenario clone base (`scenarios` above only lists
   * ones a sweep has already run).
   */
  authored_ids?: string[];
}

/** List the scenarios available in the server's active store (fast — attrs only). */
export function listScenarios() {
  return apiFetch<ScenarioListResponse>("/scenarios");
}

/** Load one scenario's trajectory as a results payload (rendered via setResults). */
export function fetchScenario(id: string) {
  return apiFetch<SimulationResults>(`/scenarios/${encodeURIComponent(id)}`);
}

/**
 * Ask every subscribed GUI tab to load scenario ``id`` (the scenario-focus
 * remote-control channel — used by external dashboards). Returns once the
 * backend has broadcast the focus.
 */
export function focusScenario(id: string) {
  return apiFetch<{ ok: boolean; scenario_id: string }>("/scenarios/focus", {
    method: "POST",
    body: JSON.stringify({ scenario_id: id }),
  });
}

/** SSE URL the GUI subscribes to for scenario-focus events. */
export const SCENARIO_FOCUS_STREAM_URL = "/api/scenarios/focus/stream";

// ---------------------------------------------------------------------------
// Scenario authoring — create/edit/delete a `scenario:` overlay on disk.
// Unlike the read helpers above (precomputed HDF5 trajectories), these edit
// the source config file so the next Run Sweep picks up the change.
// ---------------------------------------------------------------------------

export interface ScenarioSourceResponse {
  scenario_id: string;
  yaml: string;
}

/** Fetch one scenario overlay's raw YAML text (for the scoped editor). */
export function fetchScenarioSource(id: string) {
  return apiFetch<ScenarioSourceResponse>(
    `/scenarios/${encodeURIComponent(id)}/source`,
  );
}

/** Create a new scenario overlay — blank, or cloned from an existing one. */
export function createScenario(scenarioId: string, baseScenarioId?: string) {
  return apiFetch<ScenarioSourceResponse>("/scenarios", {
    method: "POST",
    body: JSON.stringify({
      scenario_id: scenarioId,
      base_scenario_id: baseScenarioId ?? null,
    }),
  });
}

/** Save edits to a scenario overlay's YAML text. */
export function updateScenario(id: string, yaml: string) {
  return apiFetch<ScenarioSourceResponse>(
    `/scenarios/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify({ yaml }) },
  );
}

/** Rename a scenario's id (its `scenario:` mapping key). */
export function renameScenario(id: string, newId: string) {
  return apiFetch<{ ok: boolean; scenario_id: string }>(
    `/scenarios/${encodeURIComponent(id)}/rename`,
    { method: "PATCH", body: JSON.stringify({ new_id: newId }) },
  );
}

/**
 * Delete a scenario overlay. Also purges its cached HDF5 group immediately,
 * if the active store has one — `cache_purged` reports whether there was
 * actually a cached result to clear.
 */
export function deleteScenario(id: string) {
  return apiFetch<{ ok: boolean; scenario_id: string; cache_purged: boolean }>(
    `/scenarios/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

/**
 * Clear every scenario's cached trajectory (deletes the whole HDF5 store).
 * Scenario definitions in the config are untouched — the next Run Sweep
 * recomputes them from scratch. `cleared` reports whether there was
 * actually a store on disk to remove.
 */
export function clearScenarioCache() {
  return apiFetch<{ ok: boolean; cleared: boolean }>("/scenarios/clear-cache", {
    method: "POST",
  });
}
