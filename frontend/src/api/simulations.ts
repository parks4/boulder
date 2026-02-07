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
  return apiFetch<StartResponse>("/simulations", {
    method: "POST",
    body: JSON.stringify({
      config,
      simulation_time: simulationTime ?? 10.0,
      time_step: timeStep ?? 1.0,
    }),
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
