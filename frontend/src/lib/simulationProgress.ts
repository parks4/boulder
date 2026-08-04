import type { SimulationProgress } from "@/types/simulation";

// Sub-steps within a single stage, in order.
// Each occupies an equal slice of that stage's bar segment.
const SUBSTEPS = ["Building", "Integrating", "Generating output"] as const;
type Substep = (typeof SUBSTEPS)[number];

function currentSubstep(buildComplete: boolean, integrationPoints: number): Substep {
  if (!buildComplete) return "Building";
  if (integrationPoints > 1) return "Integrating";
  return "Generating output";
}

/**
 * Derive a percent-complete and a human label from a single run's progress.
 *
 * Each stage owns `1/n_stages` of the bar; within a stage, each sub-step
 * (Building/Integrating/Generating output) owns an equal slice of that
 * stage's segment. Shared by every place that shows single-run progress
 * (currently `SimulationCalculatingCard`) so the bar/label logic has one
 * implementation.
 */
export function computeSimulationProgress(
  progress: SimulationProgress | null,
): { pct: number; label: string } {
  if (!progress) return { pct: 2, label: "Initializing…" };

  const stagesDone = progress.stages_done ?? 0;
  const nStages = Math.max(1, progress.n_stages ?? 1);
  const buildComplete = stagesDone >= nStages;
  const integrationPoints = progress.times?.length ?? 0;

  const substep = currentSubstep(buildComplete, integrationPoints);
  const substepIdx = SUBSTEPS.indexOf(substep); // 0, 1, or 2
  const nSubsteps = SUBSTEPS.length; // 3

  // Within the current stage, how far through the current sub-step are we?
  let substepFrac = 0;
  if (substep === "Integrating") {
    const totalTime = progress.total_time ?? 10;
    const currentTime = progress.times[integrationPoints - 1];
    substepFrac = totalTime > 0 ? Math.min(1, currentTime / totalTime) : 0;
  }

  const stageSlice = 1 / nStages;
  const substepSlice = stageSlice / nSubsteps;
  const barFrac =
    stagesDone * stageSlice + // fully solved stages
    substepIdx * substepSlice + // completed sub-steps in current stage
    substepFrac * substepSlice; // progress within current sub-step

  // Ensure at least a sliver is visible from the first poll.
  const pct = Math.max(2, Math.min(99, Math.round(barFrac * 100)));

  const stageLabel =
    nStages > 1 ? ` — stage ${Math.min(stagesDone + 1, nStages)} / ${nStages}` : "";

  return { pct, label: `${substep}${stageLabel}` };
}
