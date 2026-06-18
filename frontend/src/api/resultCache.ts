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
  config_snapshot: Record<string, unknown>;
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
 * Check whether a cached result exists for the given config.
 *
 * Unlike fetchCachedResult (which reads the server-side preloaded fingerprint),
 * this function submits the *current* in-memory config so the fingerprint is
 * computed from the same data the worker would hash — ensuring a hit even when
 * the config was updated by the SSE handler after a previous solve.
 */
export function checkSimulationCache(
  config: Record<string, unknown>,
  mechanism?: string | null,
): Promise<CacheCheckResponse> {
  return apiFetch<CacheCheckResponse>("/simulations/check-cache", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config, mechanism: mechanism ?? null }),
  });
}
