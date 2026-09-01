import { useCallback, useState, useEffect } from "react";
import type { Core as CytoscapeCore } from "cytoscape";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSolverStore } from "@/stores/solverStore";
import { useScenarioStore } from "@/stores/scenarioStore";
import { BASELINE_SCENARIO_ID } from "@/api/scenarios";
import { useSweepRunStore } from "@/stores/sweepStore";
import { fetchGuiActions, runGuiAction } from "@/api/guiActions";
import { startSimulation, stopSimulation } from "@/api/simulations";
import { checkSimulationCache } from "@/api/resultCache";
import { getSweepInfo } from "@/api/sweep";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { RunControl } from "./RunControl";
import type { GuiActionMeta } from "@/types/guiAction";
import { toast } from "sonner";

//: One host action embeds a light-background capture of the live network
//: graph in its output; no other GUI action needs one, so it is matched by
//: its registered action id.
const CALC_NOTE_ACTION_ID = "bloc_export_calculation_note";

/**
 * Capture the live Cytoscape graph as a light-background PNG (base64, no
 * data URI prefix) for a host's report export. Returns null when no
 * graph is mounted yet, or the capture itself fails — the export still
 * proceeds, just without a sheet-1 network image.
 */
function captureNetworkImagePng(): string | null {
  const cy = (window as unknown as { __boulderCy?: CytoscapeCore }).__boulderCy;
  if (!cy) return null;
  try {
    return cy.png({ bg: "#ffffff", full: true, scale: 2, output: "base64" });
  } catch {
    return null;
  }
}

export function SimulateCard() {
  const config = useConfigStore((s) => s.config);
  const fileName = useConfigStore((s) => s.fileName);
  const syncYaml = useConfigStore((s) => s.syncYaml);
  const {
    isRunning,
    simulationId,
    results,
    pythonCode,
    beginSimulationRun,
    startSimulation: setStarted,
    setError,
    setResults,
  } = useSimulationStore();
  const sweeping = useSweepRunStore((s) => s.sweeping);

  // Steady/Transient mode and its tolerances are edited from the Stage panel
  // (StageCard) — this card only needs to read them to run a simulation.
  const mode = useSolverStore((s) => s.mode);
  const kind = useSolverStore((s) => s.kind);
  const simTime = useSolverStore((s) => s.simTime);
  const timeStep = useSolverStore((s) => s.timeStep);
  const syncSolverFromConfig = useSolverStore((s) => s.syncFromConfig);

  // Only the flat "advance" kind takes a simulation_time/time_step override —
  // advance_grid/micro_step carry their own authoritative grid in
  // settings.solver, which these overrides would otherwise clobber (see
  // _resolve_run_grid in the backend).
  const sendTimeOverride = mode === "transient" && kind === "advance";

  const [guiActions, setGuiActions] = useState<GuiActionMeta[]>([]);
  const [runningActionId, setRunningActionId] = useState<string | null>(null);

  useEffect(() => {
    syncSolverFromConfig(config.settings);
  }, [config.settings, syncSolverFromConfig]);

  // A finished single run wrote a run-set entry too (its base -- BASELINE when
  // the config declares scenarios), so the Scenario pane is now stale. A sweep
  // already refreshes on completion; without this a plain run left the pane
  // reading "Not computed yet" for a scenario that had just been solved.
  useEffect(() => {
    if (results === null) return;
    void useScenarioStore.getState().refresh();
  }, [results]);

  // Re-fetch whenever config, simulationId, or results change.
  // After a solve completes (results becomes non-null), the server's cache
  // is populated and is_available will change for export actions.
  useEffect(() => {
    let cancelled = false;

    const doFetch = () =>
      syncYaml()
        .catch(() => {
          // Sync failure is non-fatal here — fall back to whatever YAML we have.
        })
        .then(() =>
          fetchGuiActions({
            config: config as unknown as Record<string, unknown>,
            config_yaml: useConfigStore.getState().originalYaml || null,
            filename: fileName,
            simulation_id: simulationId,
          }),
        )
        .then((actions) => {
          if (!cancelled) setGuiActions(actions);
        })
        .catch(() => {
          if (!cancelled) setGuiActions([]);
        });

    doFetch();

    // No second, timer-delayed fetch: the worker now stores the result before
    // it reports completion, so by the time `results` arrives the store already
    // has the entry this listing asks about.
    return () => {
      cancelled = true;
    };
  }, [config, simulationId, results, fileName, syncYaml]);

  const handleRun = useCallback(async (force = false) => {
    if (config.nodes.length === 0) {
      toast.error("Add at least one reactor before simulating");
      return;
    }

    // Run what the Scenario pane has selected, not the baseline. The server
    // resolves the id against these overlays exactly as Run Sweep does; a
    // null/BASELINE selection keeps solving the config held here (the only
    // one carrying this session's base-network edits).
    //
    // Overlays are sent even for a BASELINE run: the server's `_merged_raw`
    // uses their presence to tell whether the base config declares
    // `scenarios:` at all, which decides whether the base entry is named
    // BASELINE or BASE/`metadata.scenario_id` (see `runset.base_entry_id`).
    // Omitting them here (as this used to do whenever no named scenario was
    // selected) made a plain "Run Simulation" on BASELINE store its result
    // under the wrong name, leaving a phantom row next to the real one.
    const { activeId, overlays } = useScenarioStore.getState();
    const scenario = {
      id: activeId && activeId !== BASELINE_SCENARIO_ID ? activeId : BASELINE_SCENARIO_ID,
      overlays: overlays as Record<string, unknown>,
    };

    // Check whether a cached result already exists for the current config.
    // This avoids re-running the full simulation when nothing has changed.
    // Transient runs pass their time/step overrides so the server-side
    // fingerprint matches what an actual run would have saved. Force Run
    // skips this lookup.
    if (!force) {
      try {
        const cfgRaw = config as unknown as Record<string, unknown>;
        const phases = cfgRaw.phases as Record<string, unknown> | undefined;
        const gas = phases?.gas as Record<string, unknown> | undefined;
        const mechStr = (gas?.mechanism as string | undefined) ?? null;

        const cacheResp = await checkSimulationCache(
          cfgRaw,
          mechStr,
          sendTimeOverride ? parseFloat(simTime) : undefined,
          sendTimeOverride ? parseFloat(timeStep) : undefined,
          scenario,
        );
        if (cacheResp.cached) {
          setResults(cacheResp.result);
          const created = cacheResp.meta.created_at;
          const ageMin = Math.round((Date.now() / 1000 - created) / 60);
          const ageStr = ageMin < 2 ? "just now" : `${ageMin} min ago`;
          toast.success(`Loaded cached results from ${ageStr}. Re-run skipped.`);
          return;
        }
      } catch {
        // Cache check failed (no config path, network error, etc.) — proceed normally.
      }
    }

    beginSimulationRun();
    try {
      const resp = await startSimulation(
        config,
        sendTimeOverride ? parseFloat(simTime) : undefined,
        sendTimeOverride ? parseFloat(timeStep) : undefined,
        scenario,
      );
      setStarted(resp.simulation_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed: ${msg}`);
      setError(msg);
    }
  }, [config, simTime, timeStep, sendTimeOverride, beginSimulationRun, setStarted, setError, setResults]);

  const handleStop = useCallback(() => {
    if (!simulationId) return;
    stopSimulation(simulationId).catch((err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to stop: ${msg}`);
    });
  }, [simulationId]);

  const handleDownloadPy = useCallback(() => {
    if (!pythonCode) return;
    const blob = new Blob([pythonCode], { type: "text/x-python" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "simulation.py";
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Python code downloaded");
  }, [pythonCode]);

  const handleGuiAction = useCallback(
    async (action: GuiActionMeta) => {
      setRunningActionId(action.id);
      // An action whose cost scales with the run-set (estimated_seconds_per_
      // scenario set) gets a loading/success/error toast sharing one id, so
      // the estimate is replaced in place rather than stacked as a separate
      // toast. Boulder has no notion of what the action *does* here — the
      // ETA text uses only its own label and the generic sweep/scenario
      // count, both plugin-agnostic.
      const perScenario = action.estimated_seconds_per_scenario;
      const toastId = perScenario ? action.id : undefined;
      try {
        if (perScenario) {
          // A config with no scenarios:/sweep: block still expands to the
          // one base scenario (see boulder.runset.expand_scenarios).
          const n = await getSweepInfo()
            .then((info) => Math.max(1, info.n_scenarios))
            .catch(() => 1);
          const secs = Math.round(n * perScenario);
          toast.loading(
            `Running "${action.label}" for ${n} scenario${n === 1 ? "" : "s"}` +
              ` — ~${secs}s expected`,
            { id: toastId },
          );
        }
        try {
          await syncYaml();
        } catch {
          // Sync failure is non-fatal — fall back to whatever YAML we have.
        }
        const { blob, filename: downloadName } = await runGuiAction(action.id, {
          config: config as unknown as Record<string, unknown>,
          config_yaml: useConfigStore.getState().originalYaml || null,
          filename: fileName,
          simulation_id: simulationId,
          network_image_png:
            action.id === CALC_NOTE_ACTION_ID ? captureNetworkImagePng() : null,
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = downloadName;
        a.click();
        URL.revokeObjectURL(url);
        toast.success(`${action.label} downloaded`, { id: toastId });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error(`${action.label} failed: ${msg}`, { id: toastId });
      } finally {
        setRunningActionId(null);
      }
    },
    [config, fileName, simulationId, syncYaml],
  );

  // `sweeping` guards against launching a plain run on top of a running
  // sweep — the two share the same backend solve path and must not overlap.
  const runDisabled = isRunning || sweeping || config.nodes.length === 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 className="font-semibold text-sm text-foreground">Simulate</h3>

      <RunControl
        onRunSimulation={handleRun}
        onStopSimulation={handleStop}
        isRunning={isRunning}
        runDisabled={runDisabled}
      />

      <Button
        id="download-python"
        onClick={handleDownloadPy}
        disabled={!pythonCode}
        variant="secondary"
        className="w-full"
      >
        Download Python
      </Button>

      {guiActions.map((action) => {
        const button = (
          <Button
            key={action.id}
            id={`gui-action-${action.id}`}
            onClick={() => handleGuiAction(action)}
            disabled={
              runningActionId !== null
              || isRunning
              || !action.is_available
            }
            variant="secondary"
            className="w-full"
          >
            {runningActionId === action.id ? "Exporting..." : action.label}
          </Button>
        );
        return action.description ? (
          <Tooltip key={action.id} className="block" content={action.description}>
            {button}
          </Tooltip>
        ) : (
          button
        );
      })}
    </div>
  );
}
