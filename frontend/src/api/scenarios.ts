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
