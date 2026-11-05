import { apiFetch } from "./client";
import type { SimulationResults } from "@/types/simulation";

export interface CachedResultMeta {
  fingerprint: string;
  cache_version: number;
  created_at: number;
  boulder_version: string;
  cantera_version: string;
  mechanism: string;
}

export interface CachedResultResponse {
  cached: true;
  fingerprint: string;
  result: SimulationResults;
  meta: CachedResultMeta;
}

export interface NoCachedResultResponse {
  cached: false;
}

export type CacheCheckResponse = CachedResultResponse | NoCachedResultResponse;

export function fetchCachedResult() {
  return apiFetch<CacheCheckResponse>("/simulations/cached");
}

/**
 * Check whether a cached result exists for the run the same arguments would start.
 *
 * Unlike fetchCachedResult (which reads the server-side preloaded fingerprint),
 * the server fingerprints the entry exactly as the run would — its live config,
 * these overlays and time overrides — so a hit means the run would store the
 * same result.
 */
export function checkSimulationCache(
  simulationTime?: number,
  timeStep?: number,
  scenario?: { id: string; overlays: Record<string, unknown> },
): Promise<CacheCheckResponse> {
  return apiFetch<CacheCheckResponse>("/simulations/check-cache", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      // Transient run overrides: the server writes these into
      // settings.solver exactly like a run would, so the fingerprint
      // matches what the run stores.
      simulation_time: simulationTime ?? null,
      time_step: timeStep ?? null,
      // Same scenario selection the run itself sends (see startSimulation) —
      // otherwise this looks up the base config's fingerprint and hands back
      // the baseline result for a selected scenario.
      scenario_id: scenario?.id ?? null,
      scenarios: scenario?.overlays ?? {},
    }),
  });
}
