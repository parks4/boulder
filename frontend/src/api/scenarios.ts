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
