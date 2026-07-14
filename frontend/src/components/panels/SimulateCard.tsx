import { useCallback, useState, useEffect, useMemo } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { fetchGuiActions, runGuiAction } from "@/api/guiActions";
import { startSimulation } from "@/api/simulations";
import { checkSimulationCache } from "@/api/resultCache";
import { Button } from "@/components/ui/Button";
import { RunControl } from "./RunControl";
import type { GuiActionMeta } from "@/types/guiAction";
import { toast } from "sonner";
import { SolverDetailsModal } from "./SolverDetailsModal";
import {
  deriveMode,
  KIND_LABELS,
  KIND_TO_MODE,
  STEADY_KINDS,
  TRANSIENT_KINDS,
  type SolverKind,
  type SolverMode,
} from "./solverShared";

export function SimulateCard() {
  const config = useConfigStore((s) => s.config);
  const setConfig = useConfigStore((s) => s.setConfig);
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

  const configSolver = (config.settings as Record<string, unknown> | null | undefined)?.solver as
    | Record<string, unknown>
    | undefined;
  const configKind = configSolver?.kind as string | undefined;
  const configMode = configSolver?.mode as SolverMode | undefined;

  const [mode, setMode] = useState<SolverMode>(() =>
    configMode ?? deriveMode(configKind),
  );
  const [kind, setKind] = useState<SolverKind>(() => {
    if (configKind && configKind in KIND_TO_MODE) return configKind as SolverKind;
    return "advance_to_steady_state";
  });

  const [solverDetailsOpen, setSolverDetailsOpen] = useState(false);
  const [guiActions, setGuiActions] = useState<GuiActionMeta[]>([]);
  const [runningActionId, setRunningActionId] = useState<string | null>(null);

  const [simTime, setSimTime] = useState("10");
  const [timeStep, setTimeStep] = useState("1");

  const [rtol, setRtol] = useState("1e-9");
  const [atol, setAtol] = useState("1e-15");
  const [maxSteps, setMaxSteps] = useState("10000");

  useEffect(() => {
    const solver = (config.settings as Record<string, unknown> | null | undefined)?.solver as
      | Record<string, unknown>
      | undefined;
    const k = solver?.kind as string | undefined;
    const m = solver?.mode as SolverMode | undefined;
    const derivedMode = m ?? deriveMode(k);
    setMode(derivedMode);
    if (k && k in KIND_TO_MODE) setKind(k as SolverKind);
    if (solver?.rtol != null) setRtol(String(solver.rtol));
    if (solver?.atol != null) setAtol(String(solver.atol));
    if (solver?.max_steps != null) setMaxSteps(String(solver.max_steps));
  }, [config.settings]);

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

  const handleModeChange = useCallback(
    (newMode: SolverMode) => {
      setMode(newMode);
      const newKind = newMode === "steady" ? STEADY_KINDS[0] : TRANSIENT_KINDS[0];
      setKind(newKind);
      const currentSettings = (config.settings as Record<string, unknown>) ?? {};
      const currentSolver = (currentSettings.solver as Record<string, unknown>) ?? {};
      setConfig(
        {
          ...config,
          settings: {
            ...currentSettings,
            solver: { ...currentSolver, mode: newMode, kind: newKind },
          },
        },
        fileName,
      );
    },
    [config, fileName, setConfig],
  );

  const handleKindChange = useCallback(
    (newKind: SolverKind) => {
      setKind(newKind);
      const currentSettings = (config.settings as Record<string, unknown>) ?? {};
      const currentSolver = (currentSettings.solver as Record<string, unknown>) ?? {};
      setConfig(
        {
          ...config,
          settings: {
            ...currentSettings,
            solver: { ...currentSolver, mode: KIND_TO_MODE[newKind], kind: newKind },
          },
        },
        fileName,
      );
    },
    [config, fileName, setConfig],
  );

  // Persists tolerance and transient-grid values from the modal into
  // config.settings.solver so the backend (and Ctrl+Enter) always see them.
  const handleSolverDetailsDone = useCallback(() => {
    const currentSettings = (config.settings as Record<string, unknown>) ?? {};
    const currentSolver = (currentSettings.solver as Record<string, unknown>) ?? {};
    const rtolNum = parseFloat(rtol);
    const atolNum = parseFloat(atol);
    const maxStepsNum = parseInt(maxSteps, 10);
    const updatedSolver: Record<string, unknown> = {
      ...currentSolver,
      ...(Number.isFinite(rtolNum) ? { rtol: rtolNum } : {}),
      ...(Number.isFinite(atolNum) ? { atol: atolNum } : {}),
      ...(Number.isFinite(maxStepsNum) ? { max_steps: maxStepsNum } : {}),
      ...(mode === "transient"
        ? {
            grid: {
              stop: parseFloat(simTime),
              dt: parseFloat(timeStep),
            },
          }
        : {}),
    };
    setConfig(
      {
        ...config,
        settings: { ...currentSettings, solver: updatedSolver },
      },
      fileName,
    );
    setSolverDetailsOpen(false);
  }, [config, fileName, rtol, atol, maxSteps, mode, simTime, timeStep, setConfig]);

  // True when the loaded config has per-stage solver blocks that override the
  // global settings.solver the UI edits.
  const hasStageOverride = useMemo(() => {
    const groups = (config as unknown as Record<string, unknown>).groups as
      | Record<string, Record<string, unknown>>
      | undefined;
    if (!groups) return false;
    return Object.values(groups).some(
      (g) => typeof g?.solver === "object" && g?.solver !== null,
    );
  }, [config]);

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
  const kinds = mode === "steady" ? STEADY_KINDS : TRANSIENT_KINDS;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 className="font-semibold text-sm text-foreground">Simulate</h3>

      <div
        data-testid="solver-mode-toggle"
        className="flex rounded-md overflow-hidden border border-border text-xs font-medium"
      >
        <button
          data-testid="mode-steady"
          type="button"
          onClick={() => handleModeChange("steady")}
          className={`flex-1 py-1.5 transition-colors ${
            mode === "steady"
              ? "bg-blue-600 text-white"
              : "bg-input text-muted-foreground hover:bg-muted"
          }`}
        >
          Steady
        </button>
        <button
          data-testid="mode-transient"
          type="button"
          onClick={() => handleModeChange("transient")}
          className={`flex-1 py-1.5 transition-colors ${
            mode === "transient"
              ? "bg-teal-600 text-white"
              : "bg-input text-muted-foreground hover:bg-muted"
          }`}
        >
          Transient
        </button>
      </div>

      <div className="flex items-center gap-2">
        <p
          className="text-xs text-muted-foreground truncate flex-1 min-w-0"
          title={KIND_LABELS[kind]}
        >
          {KIND_LABELS[kind]}
        </p>
        <Button
          data-testid="open-solver-details"
          type="button"
          variant="secondary"
          size="sm"
          className="shrink-0"
          onClick={() => setSolverDetailsOpen(true)}
        >
          Solver details...
        </Button>
      </div>

      <SolverDetailsModal
        open={solverDetailsOpen}
        onClose={handleSolverDetailsDone}
        mode={mode}
        kind={kind}
        kinds={kinds}
        onKindChange={handleKindChange}
        hasStageOverride={hasStageOverride}
        rtol={rtol}
        onRtolChange={setRtol}
        atol={atol}
        onAtolChange={setAtol}
        maxSteps={maxSteps}
        onMaxStepsChange={setMaxSteps}
        simTime={simTime}
        onSimTimeChange={setSimTime}
        timeStep={timeStep}
        onTimeStepChange={setTimeStep}
      />

      <RunControl
        onRunSimulation={handleRun}
        isRunning={isRunning}
        runDisabled={runDisabled}
      />

      {simulationId && (
        <Button
          id="download-python"
          onClick={handleDownloadPy}
          disabled={!pythonCode}
          variant="secondary"
          className="w-full"
        >
          Download Python
        </Button>
      )}

      {guiActions.map((action) => (
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
      ))}
    </div>
  );
}
