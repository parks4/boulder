import { useSimulationStore } from "@/stores/simulationStore";

// Sub-steps within a single stage, in order.
// Each occupies an equal slice of that stage's bar segment.
const SUBSTEPS = ["Building", "Integrating", "Outputs"] as const;
type Substep = typeof SUBSTEPS[number];

function currentSubstep(
  buildComplete: boolean,
  integrationPoints: number,
): Substep {
  if (!buildComplete) return "Building";
  if (integrationPoints > 1) return "Integrating";
  return "Outputs";
}

export function SimulationOverlay() {
  const isRunning = useSimulationStore((s) => s.isRunning);
  const progress = useSimulationStore((s) => s.progress);

  if (!isRunning) return null;

  const stagesDone = progress?.stages_done ?? 0;
  const nStages = Math.max(1, progress?.n_stages ?? 1);
  const buildComplete = stagesDone >= nStages;
  const integrationPoints = progress?.times?.length ?? 0;

  const substep = currentSubstep(buildComplete, integrationPoints);
  const substepIdx = SUBSTEPS.indexOf(substep);          // 0, 1, or 2
  const nSubsteps = SUBSTEPS.length;                     // 3

  // Within the current stage, how far through the current sub-step are we?
  let substepFrac = 0;
  if (substep === "Integrating") {
    const totalTime = progress?.total_time ?? 10;
    const currentTime = progress!.times[integrationPoints - 1];
    substepFrac = totalTime > 0 ? Math.min(1, currentTime / totalTime) : 0;
  }

  // Each stage owns (1/nStages) of the bar.
  // Within a stage, each sub-step owns (1/nSubsteps) of that stage's slice.
  // completed stages + completed sub-steps + sub-step progress → bar fraction.
  const completedStages = buildComplete ? stagesDone : stagesDone; // stages fully done before current
  const stageSlice = 1 / nStages;
  const substepSlice = stageSlice / nSubsteps;

  const barFrac =
    completedStages * stageSlice +           // fully solved stages
    substepIdx * substepSlice +              // completed sub-steps in current stage
    substepFrac * substepSlice;              // progress within current sub-step

  // Ensure at least a sliver is visible from the first poll.
  const pct = Math.max(2, Math.min(99, Math.round(barFrac * 100)));

  const stageLabel = nStages > 1
    ? ` — stage ${Math.min(stagesDone + 1, nStages)} / ${nStages}`
    : "";
  const label = `${substep}${stageLabel}`;

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
          {progress ? label : "Initializing…"}
        </p>
      </div>
    </div>
  );
}
