import { apiFetch } from "./client";
import type { ScenarioOverlay } from "./scenarios";

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
  /**
   * Scenarios currently being solved, keyed by id — a scenario id's presence
   * here *is* "calculating". A map rather than a single "current scenario"
   * field so a future parallel sweep runner can report more than one
   * in-flight scenario at once without a shape change.
   */
  scenario_progress?: Record<
    string,
    { stage: number | null; stage_total: number | null; stage_id: string | null }
  >;
  /**
   * Latest non-empty stdout line from the sweep runner, verbatim — shown under
   * the "Calculating…" spinner so a slow solve says what it's currently doing.
   */
  last_line?: string | null;
}

/** Whether the preloaded config has a runnable sweep, and how many scenarios. */
export function getSweepInfo() {
  return apiFetch<SweepInfo>("/sweep");
}

/**
 * Start the sweep, in-process, on the server.
 *
 * `scenarios` is the caller's current in-memory scenario overlays map (see
 * `scenarioStore.ts`) — the base config comes from the server's own startup
 * snapshot, but overlays no longer live on disk, so they must be sent here
 * for the sweep to see any edits made this session. `noCache` forces a full
 * recompute, ignoring each scenario's fingerprint cache.
 */
export function startSweep(options?: {
  scenarios?: Record<string, ScenarioOverlay>;
  noCache?: boolean;
}) {
  return apiFetch<{ status: string; total: number }>("/sweep/run", {
    method: "POST",
    body: JSON.stringify({
      scenarios: options?.scenarios ?? {},
      no_cache: options?.noCache ?? false,
    }),
  });
}

/** Poll the running/last sweep job's status. */
export function getSweepStatus() {
  return apiFetch<SweepStatus>("/sweep/status");
}
