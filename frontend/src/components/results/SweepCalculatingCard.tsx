/**
 * Non-blocking "this scenario is mid-sweep" placeholder for the results area.
 *
 * Deliberately just an inline card (not a `fixed inset-0` overlay like
 * `SimulationOverlay`) — it only occupies the results card's own slot in
 * `<main>`, leaving the Scenario Pane and the rest of the layout fully
 * visible and interactive while a sweep is running.
 */
export function SweepCalculatingCard({
  scenarioId,
  stage,
}: {
  scenarioId: string;
  stage: { stage: number | null; stageTotal: number | null } | undefined;
}) {
  const stageLabel =
    stage?.stage != null && stage.stageTotal != null && stage.stageTotal > 1
      ? ` — Stage ${stage.stage}/${stage.stageTotal}`
      : "";

  return (
    <div className="rounded-lg border border-border bg-card p-6 text-center space-y-3">
      <div className="animate-spin rounded-full h-8 w-8 border-4 border-primary border-t-transparent mx-auto" />
      <p className="text-foreground font-medium">
        Calculating &quot;{scenarioId}&quot;…{stageLabel}
      </p>
    </div>
  );
}
