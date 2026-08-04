/**
 * Shared visual shell for an in-progress solve, non-blocking: it only
 * occupies the results card's own slot in `<main>`, leaving the rest of the
 * layout (Scenario Pane, network graph, ...) fully visible and interactive.
 * Used by both `SweepCalculatingCard` (a sweep scenario) and
 * `SimulationCalculatingCard` (a plain Run Simulation) so the two share one
 * rendering instead of two near-identical cards.
 */
export function CalculatingCardShell({
  headline,
  detailLine,
  pct,
}: {
  headline: string;
  /** Latest console line or sub-step label shown under the headline. */
  detailLine?: string | null;
  /** Percent complete (0-100); omit to show a plain spinner with no bar. */
  pct?: number;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-6 text-center space-y-3">
      <div className="animate-spin rounded-full h-8 w-8 border-4 border-primary border-t-transparent mx-auto" />
      <div className="space-y-1">
        <p className="text-foreground font-medium">{headline}</p>
        {pct != null && (
          <div className="w-full bg-muted rounded-full h-2">
            <div
              className="bg-primary h-2 rounded-full transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
        {detailLine && (
          <p
            className="text-xs text-muted-foreground font-mono truncate"
            title={detailLine}
          >
            {detailLine}
          </p>
        )}
      </div>
    </div>
  );
}
