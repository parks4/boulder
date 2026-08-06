import { useSimulationStore } from "@/stores/simulationStore";
import { useSweepRunStore } from "@/stores/sweepStore";

/**
 * "stopping" is derived, not stored: both backends already carry it in the
 * payload the client already polls/streams (`progress.is_stopping` for a
 * single run, `SweepStatus.status === "stopping"` for a sweep — see
 * sweepStore.ts's `stopping` field), so there is nothing here that could
 * strand a stale flag on completion/error.
 */
export type RunPhase = "idle" | "running" | "stopping";

/** Derive the run phase for a plain "Run Simulation". */
export function useSimulationRunPhase(): RunPhase {
  const isRunning = useSimulationStore((s) => s.isRunning);
  const isStopping = useSimulationStore((s) => s.progress?.is_stopping ?? false);
  if (!isRunning) return "idle";
  return isStopping ? "stopping" : "running";
}

/** Derive the run phase for a sweep. */
export function useSweepRunPhase(): RunPhase {
  const sweeping = useSweepRunStore((s) => s.sweeping);
  const stopping = useSweepRunStore((s) => s.stopping);
  if (!sweeping) return "idle";
  return stopping ? "stopping" : "running";
}
