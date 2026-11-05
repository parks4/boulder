import { apiFetch } from "./client";
import type { SimulationResults } from "@/types/simulation";

interface StartResponse {
  simulation_id: string;
}

/**
 * Start a run. The server expands its own live config (the one the browser last
 * synced) with *scenario.overlays* and solves the run-set entry *scenario.id*
 * (BASELINE: the base entry) — the same pipeline Run Sweep uses — then stores
 * the result under that id. *force* solves even when the store holds it.
 */
export function startSimulation(
  simulationTime?: number,
  timeStep?: number,
  scenario?: { id: string; overlays: Record<string, unknown> },
  force = false,
) {
  const body: Record<string, unknown> = {};
  if (simulationTime !== undefined) body.simulation_time = simulationTime;
  if (timeStep !== undefined) body.time_step = timeStep;
  if (scenario) {
    body.scenario_id = scenario.id;
    body.scenarios = scenario.overlays;
  }
  if (force) body.force = true;
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
