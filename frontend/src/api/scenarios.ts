import { apiFetch } from "./client";
import type { SimulationResults } from "@/types/simulation";
import type { ConfigConnection, ConfigNode } from "@/types/config";

/**
 * The unmodified base config's own synthesized run-set entry (mirrors
 * `boulder.runset.BASELINE_SCENARIO_ID`) -- not a real `scenarios:` overlay
 * key, so it has no overlay subtree to edit/delete like an authored scenario.
 */
export const BASELINE_SCENARIO_ID = "BASELINE";

/** A scenario overlay -- whatever subtree lives under `scenarios.<id>:` in STONE. */
export type ScenarioOverlay = Record<string, unknown>;

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
  /**
   * Display unit per host-supplied KPI attr key (e.g. `{ efficiency: "%" }`),
   * for `scenario_attrs` values returned as `(value, unit)` — see
   * `boulder.sweep_runner.run`'s docstring. Auto-walked node/connection input
   * attrs (`in.<id>.<prop>` keys) aren't in here; their unit is resolved on
   * the frontend from the property name (see `SweepResultsPlot.tsx`).
   */
  units?: Record<string, string> | null;
  /**
   * Attr keys that are bookkeeping, not plottable KPIs. Sent by the server
   * (`scenario_store.NON_KPI_ATTRS`) instead of mirrored here: the local copy
   * drifted as soon as the store gained an attr, and `store_version` showed up
   * as a selectable Sweep Results axis.
   */
  non_kpi_keys?: string[] | null;
  scenarios: ScenarioMeta[];
  /**
   * Every scenario id in the config's `scenario:` mapping, regardless of
   * whether a sweep has computed it yet — the source of truth for what can
   * be used as an Add Scenario clone base (`scenarios` above only lists
   * ones a sweep has already run).
   */
  authored_ids?: string[];
  /**
   * The `scenarios:` block as loaded at server startup — the one-time seed
   * for this store's own `overlays` state. Scenario authoring is in-memory
   * from here on (see `scenarioStore.ts`); this is never re-fetched.
   */
  authored_overlays?: Record<string, ScenarioOverlay>;
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
// Scenario authoring — create/edit/delete a scenario overlay, in memory only.
//
// Nothing here writes to disk: every call below is a stateless transform —
// it sends the *current* overlays map (this store's own state) and gets back
// the *new* one. The backend never keeps a copy between calls, exactly like
// `/configs/parse` already treats the base config. The only way to get a
// scenario onto disk is `renderFullYaml` + a client-side download.
// ---------------------------------------------------------------------------

export interface ScenarioSourceResponse {
  scenario_id: string;
  yaml: string;
}

/** Render one scenario overlay's YAML text (for the scoped editor). */
export function fetchScenarioSource(id: string, overlay: ScenarioOverlay) {
  return apiFetch<ScenarioSourceResponse>(
    `/scenarios/${encodeURIComponent(id)}/source`,
    { method: "POST", body: JSON.stringify({ overlay }) },
  );
}

export interface ScenarioPreviewResponse {
  scenario_id: string;
  nodes: ConfigNode[];
  connections: ConfigConnection[];
}

/**
 * Fetch one scenario's effective node/connection properties (base config
 * deep-merged with *overlay*) — works before Run Sweep has ever solved it,
 * unlike `fetchScenario` (which 404s until a trajectory is cached). Send an
 * empty overlay for BASELINE.
 */
export function fetchScenarioPreview(id: string, overlay: ScenarioOverlay) {
  return apiFetch<ScenarioPreviewResponse>(
    `/scenarios/${encodeURIComponent(id)}/preview`,
    { method: "POST", body: JSON.stringify({ overlay }) },
  );
}

/**
 * Render the full merged config (base ⊕ *overlay*) as YAML text — backs the
 * Scenario YAML pane's "Download full YAML" button, the one sanctioned way
 * to get an edited scenario onto disk.
 */
export function renderFullYaml(id: string, overlay: ScenarioOverlay) {
  return apiFetch<ScenarioSourceResponse>(
    `/scenarios/${encodeURIComponent(id)}/render-full`,
    { method: "POST", body: JSON.stringify({ overlay }) },
  );
}

export interface ScenarioMutationResponse extends ScenarioSourceResponse {
  overlays: Record<string, ScenarioOverlay>;
}

/** Create a new scenario overlay — blank, or cloned from an existing one. */
export function createScenario(
  overlays: Record<string, ScenarioOverlay>,
  scenarioId: string,
  baseScenarioId?: string,
  description?: string,
) {
  return apiFetch<ScenarioMutationResponse>("/scenarios", {
    method: "POST",
    body: JSON.stringify({
      overlays,
      scenario_id: scenarioId,
      base_scenario_id: baseScenarioId ?? null,
      description: description || null,
    }),
  });
}

/** Apply edits to a scenario overlay's YAML text. */
export function updateScenario(
  overlays: Record<string, ScenarioOverlay>,
  id: string,
  yaml: string,
) {
  return apiFetch<ScenarioMutationResponse>(
    `/scenarios/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify({ overlays, yaml }) },
  );
}

export interface ScenarioEntityUpdateResponse {
  scenario_id: string;
  id: string;
  yaml: string;
  overlays: Record<string, ScenarioOverlay>;
}

/**
 * Merge edited properties into one node/connection's overlay entry for this
 * scenario -- backs the Properties panel's "Save" while a scenario is
 * active, so the edit lands in the scenario's overlay instead of the base
 * network. Whether `entityId` is a node or connection, and which stage list
 * it belongs to, is resolved server-side from the base config itself.
 */
export function updateScenarioEntity(
  overlays: Record<string, ScenarioOverlay>,
  scenarioId: string,
  entityId: string,
  properties: Record<string, unknown>,
) {
  return apiFetch<ScenarioEntityUpdateResponse>(
    `/scenarios/${encodeURIComponent(scenarioId)}/entities/${encodeURIComponent(entityId)}`,
    { method: "PATCH", body: JSON.stringify({ overlays, properties }) },
  );
}

export interface RenameScenarioResponse {
  ok: boolean;
  scenario_id: string;
  overlays: Record<string, ScenarioOverlay>;
}

/** Rename a scenario's id (its overlays-map key). */
export function renameScenario(
  overlays: Record<string, ScenarioOverlay>,
  id: string,
  newId: string,
) {
  return apiFetch<RenameScenarioResponse>(
    `/scenarios/${encodeURIComponent(id)}/rename`,
    { method: "PATCH", body: JSON.stringify({ overlays, new_id: newId }) },
  );
}

export interface DeleteScenarioResponse {
  ok: boolean;
  scenario_id: string;
  cache_purged: boolean;
  overlays: Record<string, ScenarioOverlay>;
}

/**
 * Delete a scenario overlay. Also purges its cached HDF5 group immediately,
 * if the active store has one — `cache_purged` reports whether there was
 * actually a cached result to clear.
 */
export function deleteScenario(overlays: Record<string, ScenarioOverlay>, id: string) {
  return apiFetch<DeleteScenarioResponse>(`/scenarios/${encodeURIComponent(id)}`, {
    method: "DELETE",
    body: JSON.stringify({ overlays }),
  });
}

/**
 * Clear every scenario's cached trajectory (deletes the whole HDF5 store).
 * Scenario definitions are untouched — this only ever affected the results
 * cache. `cleared` reports whether there was actually a store on disk to
 * remove.
 */
export function clearScenarioCache() {
  return apiFetch<{ ok: boolean; cleared: boolean }>("/scenarios/clear-cache", {
    method: "POST",
  });
}
