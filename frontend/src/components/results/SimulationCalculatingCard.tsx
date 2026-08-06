import { useSimulationStore } from "@/stores/simulationStore";
import { computeSimulationProgress } from "@/lib/simulationProgress";
import { CalculatingCardShell } from "./CalculatingCardShell";

/**
 * "A plain Run Simulation is in progress" placeholder for the results area —
 * the single-run analog of `SweepCalculatingCard`, sharing the same
 * non-blocking shell instead of the `fixed inset-0` overlay this used to be.
 */
export function SimulationCalculatingCard() {
  const isRunning = useSimulationStore((s) => s.isRunning);
  const progress = useSimulationStore((s) => s.progress);

  if (!isRunning) return null;

  const { pct, label } = computeSimulationProgress(progress);
  const stopping = progress?.is_stopping ?? false;

  return (
    <CalculatingCardShell
      headline={stopping ? "Stopping simulation…" : "Simulation running…"}
      detailLine={label}
      pct={pct}
      stopping={stopping}
    />
  );
}
