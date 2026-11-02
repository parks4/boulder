import { useEffect, useState } from "react";
import { BASELINE_SCENARIO_ID } from "@/api/scenarios";
import { parseHostStatus, type HostStatus } from "@/lib/hostStatus";
import { useConfigStore } from "@/stores/configStore";
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
 * Top-bar chip showing the host's status for the scenario on screen
 * (`plugins.header_status`), resolved by the server at
 * `GET /api/ui/header-status`: the GUI sends only the scenario id (nothing for
 * the base run) and the server finds the config and stored fingerprints.
 *
 * Re-queried, never on a timer, when the selected scenario changes, a result
 * lands (single run or cached reopen), a sweep ends, or `config.metadata`
 * changes. While a run or sweep is in flight nothing is asked, and the chip is
 * hidden when the scenario changes and during a run. A null status, or a 404 (a
 * scenario that exists only in the pane), renders nothing.
 */
export function HeaderStatus() {
  const activeId = useScenarioStore((s) => s.activeId);
  const results = useSimulationStore((s) => s.results);
  const isRunning = useSimulationStore((s) => s.isRunning);
  const sweeping = useSweepRunStore((s) => s.sweeping);
  const metadata = useConfigStore((s) => s.config.metadata);
  const [status, setStatus] = useState<HostStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // The scenario the shown answer is about: never show it against another one.
  const [answeredFor, setAnsweredFor] = useState<string | null>(null);

  useEffect(() => {
    if (isRunning || sweeping) return;
    let stale = false;
    const query =
      activeId && activeId !== BASELINE_SCENARIO_ID
        ? `?${new URLSearchParams({ scenario_id: activeId })}`
        : "";
    fetch(`/api/ui/header-status${query}`)
      .then(async (r) => {
        if (r.ok) return r.json();
        // 404: a scenario that exists only in the pane has nothing to report.
        if (r.status === 404) return { status: null };
        // The server's 500 carries the provider's failure as `detail`.
        const body = await r.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string" ? body.detail : `HTTP ${r.status}`,
        );
      })
      .then((data) => {
        const parsed = parseHostStatus(data);
        if (!stale) {
          setStatus(parsed);
          setFailure(null);
          setAnsweredFor(activeId ?? "");
        }
      })
      .catch((err: unknown) => {
        if (stale) return;
        setStatus(null);
        setAnsweredFor(activeId ?? "");
        setFailure(err instanceof Error ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [activeId, results, isRunning, sweeping, metadata]);

  if (answeredFor !== (activeId ?? "") || isRunning || sweeping) return null;
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
  const title = status.tooltip ?? undefined;
  return status.href ? (
    <a
      data-testid="header-status"
      data-tone={status.tone}
      href={status.href}
      title={title}
      {...(status.new_tab ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className={`${className} hover:bg-muted`}
    >
      {status.text}
    </a>
  ) : (
    <span data-testid="header-status" data-tone={status.tone} title={title} className={className}>
      {status.text}
    </span>
  );
}
