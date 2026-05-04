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

export function stopSimulation(simId: string) {
  return apiFetch<{ stopped: boolean }>(`/simulations/${simId}`, {
    method: "DELETE",
  });
}
