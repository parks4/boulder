import { apiFetch } from "./client";

export interface SweepInfo {
  available: boolean;
  n_scenarios: number;
  can_run: boolean;
  reason: string;
  running: boolean;
  /** ``--sweep`` launched the GUI in sweep mode → default the button to Run Sweep. */
  default?: boolean;
  /** ``--run`` launched the GUI → auto-start the run once on load. */
  autorun?: boolean;
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

/**
 * Start the sweep as a background batch job on the server.
 *
 * `noCache` is the "Regenerate cache" action: the server sets
 * `BOULDER_NO_CACHE=1` for the runner subprocess, so every scenario is
 * re-solved instead of skipping ones whose fingerprint is unchanged.
 */
export function startSweep(options?: { noCache?: boolean }) {
  return apiFetch<{ status: string; total: number }>("/sweep/run", {
    method: "POST",
    body: JSON.stringify({ no_cache: options?.noCache ?? false }),
  });
}

/** Poll the running/last sweep job's status. */
export function getSweepStatus() {
  return apiFetch<SweepStatus>("/sweep/status");
}
