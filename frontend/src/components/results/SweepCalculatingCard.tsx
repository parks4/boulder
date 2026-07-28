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
  lastLine,
}: {
  scenarioId: string;
  stage: { stage: number | null; stageTotal: number | null } | undefined;
  /**
   * Latest console line from the sweep runner, shown verbatim under the
   * headline so a long solve says what it's actually doing. Truncated to one
   * line — the full stream is on the server console.
   */
  lastLine?: string | null;
}) {
  const stageLabel =
    stage?.stage != null && stage.stageTotal != null && stage.stageTotal > 1
      ? ` — Stage ${stage.stage}/${stage.stageTotal}`
      : "";

  return (
    <div className="rounded-lg border border-border bg-card p-6 text-center space-y-3">
      <div className="animate-spin rounded-full h-8 w-8 border-4 border-primary border-t-transparent mx-auto" />
      <div className="space-y-1">
        <p className="text-foreground font-medium">
          Calculating &quot;{scenarioId}&quot;…{stageLabel}
        </p>
        {lastLine && (
          <p
            className="text-xs text-muted-foreground font-mono truncate"
            title={lastLine}
          >
            {lastLine}
          </p>
        )}
      </div>
    </div>
  );
}
