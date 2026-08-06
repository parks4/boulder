import { apiFetch } from "./client";
import type { NormalizedConfig } from "@/types/config";
import type { SimulationResults } from "@/types/simulation";

interface StartResponse {
  simulation_id: string;
}

export function startSimulation(
  config: NormalizedConfig,
  simulationTime?: number,
  timeStep?: number,
) {
  const body: Record<string, unknown> = { config };
  if (simulationTime !== undefined) body.simulation_time = simulationTime;
  if (timeStep !== undefined) body.time_step = timeStep;
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
