import { useCallback, useState, useEffect, useMemo } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { startSimulation } from "@/api/simulations";
import { Button } from "@/components/ui/Button";
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
  const {
    isRunning,
    simulationId,
    pythonCode,
    beginSimulationRun,
    startSimulation: setStarted,
    setError,
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

  const handleRun = useCallback(async () => {
    if (config.nodes.length === 0) {
      toast.error("Add at least one reactor before simulating");
      return;
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
  }, [config, simTime, timeStep, mode, beginSimulationRun, setStarted, setError]);

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

  const runDisabled = isRunning || config.nodes.length === 0;
  const runVariant = runDisabled ? "muted" : "success";
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

      <Button
        id="run-simulation"
        onClick={handleRun}
        disabled={runDisabled}
        variant={runVariant}
        className="w-full"
      >
        {isRunning ? "Running..." : "Run Simulation (Ctrl+Enter)"}
      </Button>

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
    </div>
  );
}
