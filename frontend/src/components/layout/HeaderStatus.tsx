import { useEffect, useState } from "react";
import { BASELINE_SCENARIO_ID } from "@/api/scenarios";
import { parseHostStatus, type HostStatus } from "@/lib/hostStatus";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSweepRunStore } from "@/stores/sweepStore";

const TONE_CLASS: Record<HostStatus["tone"], string> = {
  ok: "border-success text-success",
  warn: "border-amber-500 text-amber-500",
  error: "border-destructive text-destructive",
  neutral: "border-border text-muted-foreground",
};

const UNAVAILABLE_TEXT = "status unavailable";

/**
 * Top-bar chip showing one host status endpoint's answer for the scenario on
 * screen (`plugins.add_header_status`).
 *
 * Re-queried on exactly two triggers, never on a timer: the selected scenario
 * changes, and a solve finishes (single run, cached reopen, or sweep). While a
 * run or sweep is in flight nothing is asked. The fingerprint is sent only when
 * the GUI holds one (see `simulationStore.fingerprint`).
 */
export function HeaderStatus({ statusUrl }: { statusUrl: string }) {
  const activeId = useScenarioStore((s) => s.activeId) ?? BASELINE_SCENARIO_ID;
  const results = useSimulationStore((s) => s.results);
  const fingerprint = useSimulationStore((s) => s.fingerprint);
  const isRunning = useSimulationStore((s) => s.isRunning);
  const sweeping = useSweepRunStore((s) => s.sweeping);
  const [status, setStatus] = useState<HostStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (isRunning || sweeping) return;
    let stale = false;
    const params = new URLSearchParams({ scenario: activeId });
    if (fingerprint) params.set("fingerprint", fingerprint);
    fetch(`${statusUrl}?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        const parsed = parseHostStatus(data);
        if (!stale) {
          setStatus(parsed);
          setFailure(null);
        }
      })
      .catch((err: unknown) => {
        if (stale) return;
        setStatus(null);
        setFailure(err instanceof Error ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [statusUrl, activeId, results, fingerprint, isRunning, sweeping]);

  if (failure !== null) {
    return (
      <span
        data-testid="header-status"
        data-tone="neutral"
        title={failure}
        className={`text-sm px-2 py-1 rounded border ${TONE_CLASS.neutral}`}
      >
        {UNAVAILABLE_TEXT}
      </span>
    );
  }
  if (status === null) return null;
  const className = `text-sm px-2 py-1 rounded border ${TONE_CLASS[status.tone]}`;
  return status.href ? (
    <a
      data-testid="header-status"
      data-tone={status.tone}
      href={status.href}
      title={status.tooltip}
      className={`${className} hover:bg-muted`}
    >
      {status.text}
    </a>
  ) : (
    <span data-testid="header-status" data-tone={status.tone} title={status.tooltip} className={className}>
      {status.text}
    </span>
  );
}
