import { create } from "zustand";
import { toast } from "sonner";
import { getSweepStatus, startSweep } from "@/api/sweep";
import { useScenarioStore } from "./scenarioStore";

interface SweepRunState {
  sweeping: boolean;
  progress: { current: number; total: number };
  /**
   * Start a sweep job and poll it to completion, toasting the outcome and
   * refreshing the Scenario Pane. Backs RunControl's "Run Sweep" — a single
   * shared job so any other caller can't disagree about whether a sweep is
   * currently running. `noCache` forces a full recompute, ignoring the
   * store's per-scenario fingerprint cache (see `startSweep`).
   */
  run: (options?: { total?: number; noCache?: boolean }) => void;
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

export const useSweepRunStore = create<SweepRunState>((set, get) => ({
  sweeping: false,
  progress: { current: 0, total: 0 },

  run: (options) => {
    if (get().sweeping) {
      toast.error("A sweep is already running");
      return;
    }
    set({ sweeping: true, progress: { current: 0, total: options?.total ?? 0 } });
    startSweep({ noCache: options?.noCache })
      .then(() => {
        pollHandle = setInterval(() => {
          getSweepStatus()
            .then((st) => {
              if (st.status === "running") {
                set({ progress: { current: st.current ?? 0, total: st.total ?? 0 } });
                return;
              }
              stopPolling();
              set({ sweeping: false });
              if (st.status === "done") {
                toast.success("Sweep complete — scenarios updated");
                void useScenarioStore.getState().refresh();
              } else {
                toast.error(`Sweep failed: ${st.message ?? "unknown error"}`);
              }
            })
            .catch(() => {
              stopPolling();
              set({ sweeping: false });
            });
        }, 1000);
      })
      .catch((e) => {
        set({ sweeping: false });
        toast.error(e instanceof Error ? e.message : String(e));
      });
  },
}));
