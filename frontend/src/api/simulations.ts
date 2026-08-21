import { apiFetch } from "./client";
import type { NormalizedConfig } from "@/types/config";
import type { SimulationResults } from "@/types/simulation";

interface StartResponse {
  simulation_id: string;
}

/**
 * Start a run. When *scenario* is given, the server solves that run-set entry
 * (base config ⊕ *scenario.overlays*) instead of *config* — the same
 * expansion Run Sweep uses — and stores the result under that scenario id.
 * BASELINE is passed as-is and keeps solving *config*.
 */
export function startSimulation(
  config: NormalizedConfig,
  simulationTime?: number,
  timeStep?: number,
  scenario?: { id: string; overlays: Record<string, unknown> },
) {
  const body: Record<string, unknown> = { config };
  if (simulationTime !== undefined) body.simulation_time = simulationTime;
  if (timeStep !== undefined) body.time_step = timeStep;
  if (scenario) {
    body.scenario_id = scenario.id;
    body.scenarios = scenario.overlays;
  }
  return apiFetch<StartResponse>("/simulations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchSimulationResults(simId: string) {
  return apiFetch<SimulationResults>(`/simulations/${simId}/results`);
}

/**
 * Request that a running simulation stop. Cooperative, not immediate: the
 * request returns right away; the actual wind-down is observed via the SSE
 * stream's "stopped" event (see useSimulationSSE.ts).
 */
export function stopSimulation(simId: string) {
  return apiFetch<{ stopping: boolean; simulation_id: string }>(
    `/simulations/${simId}`,
    { method: "DELETE" },
  );
}
