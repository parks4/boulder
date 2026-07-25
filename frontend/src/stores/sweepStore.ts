import { create } from "zustand";
import { toast } from "sonner";
import { getSweepStatus, startSweep, type SweepStatus } from "@/api/sweep";
import { useScenarioStore } from "./scenarioStore";

interface SweepRunState {
  sweeping: boolean;
  progress: { current: number; total: number };
  /**
   * Scenarios currently being solved, keyed by id (mirrors
   * `SweepStatus.scenario_progress` — see that type for why it's a map).
   */
  scenarioProgress: Record<string, { stage: number | null; stageTotal: number | null }>;
  /**
   * Start a sweep job and poll it to completion, toasting the outcome and
   * refreshing the Scenario Pane. Backs RunControl's "Run Sweep" — a single
   * shared job so any other caller can't disagree about whether a sweep is
   * currently running. `noCache` forces a full recompute, ignoring the
   * store's per-scenario fingerprint cache (see `startSweep`).
   */
  run: (options?: { total?: number; noCache?: boolean }) => void;
  /**
   * Attach to a sweep that's already running server-side (e.g. the page was
   * refreshed mid-sweep) — a no-op if nothing is running, or if this session
   * is already polling one via `run()`.
   */
  hydrate: () => void;
}

// Module-level (not store state) — a plain interval handle, not observed by
// React; only one ever exists regardless of how many components call run().
let pollHandle: ReturnType<typeof setInterval> | null = null;

function stopPolling(): void {
  if (pollHandle !== null) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

export const useSweepRunStore = create<SweepRunState>((set, get) => {
  // Single place that interprets a status payload — `run()`'s poll tick and
  // `hydrate()`'s first snapshot both funnel through this, so there is only
  // ever one poll loop and one completion path regardless of who started it.
  function applyStatus(st: SweepStatus): void {
    if (st.status === "running") {
      const scenarioProgress: SweepRunState["scenarioProgress"] = {};
      for (const [id, p] of Object.entries(st.scenario_progress ?? {})) {
        scenarioProgress[id] = { stage: p.stage, stageTotal: p.stage_total };
      }
      set({
        sweeping: true,
        progress: { current: st.current ?? 0, total: st.total ?? 0 },
        scenarioProgress,
      });
      return;
    }
    stopPolling();
    set({ sweeping: false, scenarioProgress: {} });
    if (st.status === "done") {
      toast.success("Sweep complete — scenarios updated");
      void (async () => {
        await useScenarioStore.getState().refresh();
        // The active scenario may have only just finished solving — re-fetch
        // it now that it's actually in the store, replacing whatever
        // "calculating" placeholder was showing.
        const { activeId, scenarios, setActive } = useScenarioStore.getState();
        if (activeId && scenarios.some((s) => s.id === activeId)) {
          void setActive(activeId);
        } else if (scenarios.length > 0) {
          // Nothing was selected before the sweep ran (e.g. the first sweep
          // in a session) — auto-select a scenario so the results view
          // populates instead of staying blank behind the Scenario Pane.
          void setActive(scenarios[0].id);
        }
      })();
    } else if (st.status === "error") {
      toast.error(`Sweep failed: ${st.message ?? "unknown error"}`);
    }
    // "idle" only ever reaches here from hydrate()'s no-op path below, never
    // from an active poll tick — nothing to do, no toast.
  }

  function startPolling(): void {
    if (pollHandle !== null) return; // a loop is already running
    pollHandle = setInterval(() => {
      getSweepStatus()
        .then(applyStatus)
        .catch(() => {
          stopPolling();
          set({ sweeping: false });
        });
    }, 1000);
  }

  return {
    sweeping: false,
    progress: { current: 0, total: 0 },
    scenarioProgress: {},

    run: (options) => {
      if (get().sweeping) {
        toast.error("A sweep is already running");
        return;
      }
      set({ sweeping: true, progress: { current: 0, total: options?.total ?? 0 } });
      startSweep({ noCache: options?.noCache })
        .then(() => startPolling())
        .catch((e) => {
          set({ sweeping: false });
          toast.error(e instanceof Error ? e.message : String(e));
        });
    },

    hydrate: () => {
      if (get().sweeping) return; // this session's own run() is already attached
      getSweepStatus()
        .then((st) => {
          if (st.status !== "running") return; // nothing in flight
          applyStatus(st);
          startPolling();
        })
        .catch(() => {
          // Best-effort — if the backend isn't reachable yet, a later
          // manual Run Sweep click will surface the real error.
        });
    },
  };
});
