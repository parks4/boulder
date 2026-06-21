import { apiFetch } from "./client";

export interface SweepInfo {
  available: boolean;
  n_scenarios: number;
  can_run: boolean;
  reason: string;
  running: boolean;
}

export interface SweepStatus {
  status: "idle" | "running" | "done" | "error";
  current?: number;
  total?: number;
  message?: string;
}

/** Whether the preloaded config has a runnable sweep, and how many scenarios. */
export function getSweepInfo() {
  return apiFetch<SweepInfo>("/sweep");
}

/** Start the sweep as a background batch job on the server. */
export function startSweep() {
  return apiFetch<{ status: string; total: number }>("/sweep/run", {
    method: "POST",
    body: "{}",
  });
}

/** Poll the running/last sweep job's status. */
export function getSweepStatus() {
  return apiFetch<SweepStatus>("/sweep/status");
}
