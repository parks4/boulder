import { useSimulationStore } from "@/stores/simulationStore";

export function SimulationOverlay() {
  const isRunning = useSimulationStore((s) => s.isRunning);
  const progress = useSimulationStore((s) => s.progress);

  if (!isRunning) return null;

  const totalTime = progress?.total_time ?? 10;
  const currentTime = progress?.times?.length
    ? progress.times[progress.times.length - 1]
    : 0;
  const pct =
    totalTime > 0
      ? Math.min(100, Math.round((currentTime / totalTime) * 100))
      : 0;

  return (
    <div
      id="simulation-overlay"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/50"
    >
      <div className="bg-card border border-border rounded-lg shadow-lg p-8 text-center space-y-3 max-w-sm">
        <div className="animate-spin rounded-full h-10 w-10 border-4 border-primary border-t-transparent mx-auto" />
        <p className="text-foreground font-medium">Simulation Running...</p>
        <div className="w-full bg-muted rounded-full h-2">
          <div
            className="bg-primary h-2 rounded-full transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          {progress
            ? `${pct}% — ${progress.times.length} time steps`
            : "Initializing..."}
        </p>
      </div>
    </div>
  );
}
