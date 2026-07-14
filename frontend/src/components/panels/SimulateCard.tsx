import { useCallback, useState, useEffect } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSolverStore } from "@/stores/solverStore";
import { fetchGuiActions, runGuiAction } from "@/api/guiActions";
import { startSimulation } from "@/api/simulations";
import { checkSimulationCache } from "@/api/resultCache";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { RunControl } from "./RunControl";
import type { GuiActionMeta } from "@/types/guiAction";
import { toast } from "sonner";

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

  // Steady/Transient mode and its tolerances are edited from the Stage panel
  // (StageCard) — this card only needs to read them to run a simulation.
  const mode = useSolverStore((s) => s.mode);
  const simTime = useSolverStore((s) => s.simTime);
  const timeStep = useSolverStore((s) => s.timeStep);
  const syncSolverFromConfig = useSolverStore((s) => s.syncFromConfig);

  const [guiActions, setGuiActions] = useState<GuiActionMeta[]>([]);
  const [runningActionId, setRunningActionId] = useState<string | null>(null);

  useEffect(() => {
    syncSolverFromConfig(config.settings);
  }, [config.settings, syncSolverFromConfig]);

  // Re-fetch whenever config, simulationId, or results change.
  // After a solve completes (results becomes non-null), the server's cache
  // is populated and is_available will change for export actions.
  // A second fetch fires after a short delay to catch the (async) cache write.
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

    // When results just arrived, fire a second fetch after the background
    // cache-write thread has had time to finish (~3 s is conservative).
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (results !== null) {
      timer = setTimeout(doFetch, 3000);
    }

    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [config, simulationId, results, fileName, syncYaml]);

  const handleRun = useCallback(async (force = false) => {
    if (config.nodes.length === 0) {
      toast.error("Add at least one reactor before simulating");
      return;
    }

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
          mode === "transient" ? parseFloat(simTime) : undefined,
          mode === "transient" ? parseFloat(timeStep) : undefined,
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
        mode === "transient" ? parseFloat(simTime) : undefined,
        mode === "transient" ? parseFloat(timeStep) : undefined,
      );
      setStarted(resp.simulation_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed: ${msg}`);
      setError(msg);
    }
  }, [config, simTime, timeStep, mode, beginSimulationRun, setStarted, setError, setResults]);

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
      try {
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
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = downloadName;
        a.click();
        URL.revokeObjectURL(url);
        toast.success(`${action.label} downloaded`);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error(`${action.label} failed: ${msg}`);
      } finally {
        setRunningActionId(null);
      }
    },
    [config, fileName, simulationId, syncYaml],
  );

  const runDisabled = isRunning || config.nodes.length === 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 className="font-semibold text-sm text-foreground">Simulate</h3>

      <RunControl
        onRunSimulation={handleRun}
        isRunning={isRunning}
        runDisabled={runDisabled}
      />

      <Tooltip
        className="block"
        content="Download the equivalent runnable Python/Cantera script for this network."
      >
        <Button
          id="download-python"
          onClick={handleDownloadPy}
          disabled={!pythonCode}
          variant="secondary"
          className="w-full"
        >
          Download Python
        </Button>
      </Tooltip>

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
