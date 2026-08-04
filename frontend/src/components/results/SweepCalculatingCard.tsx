import { CalculatingCardShell } from "./CalculatingCardShell";

/**
 * "This scenario is mid-sweep" placeholder for the results area — see
 * `CalculatingCardShell` for why it's a non-blocking inline card rather than
 * a `fixed inset-0` overlay.
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
    <CalculatingCardShell
      headline={`Calculating "${scenarioId}"…${stageLabel}`}
      detailLine={lastLine}
    />
  );
}
