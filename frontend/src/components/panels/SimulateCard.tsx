import { useCallback, useState, useEffect } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { startSimulation } from "@/api/simulations";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

type SolverMode = "steady" | "transient";

type SteadyKind = "advance_to_steady_state" | "solve_steady";
type TransientKind = "advance" | "advance_grid" | "micro_step";
type SolverKind = SteadyKind | TransientKind;

const STEADY_KINDS: SteadyKind[] = ["advance_to_steady_state", "solve_steady"];
const TRANSIENT_KINDS: TransientKind[] = ["advance", "advance_grid", "micro_step"];

const KIND_LABELS: Record<SolverKind, string> = {
  advance_to_steady_state: "advance_to_steady_state",
  solve_steady: "solve_steady",
  advance: "advance",
  advance_grid: "advance_grid",
  micro_step: "micro_step",
};

const KIND_TO_MODE: Record<SolverKind, SolverMode> = {
  advance_to_steady_state: "steady",
  solve_steady: "steady",
  advance: "transient",
  advance_grid: "transient",
  micro_step: "transient",
};

function deriveMode(kind: string | undefined): SolverMode {
  if (!kind) return "steady";
  return KIND_TO_MODE[kind as SolverKind] ?? "steady";
}

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

  // Derive initial mode/kind from config.settings.solver
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

  // Transient fields
  const [simTime, setSimTime] = useState("10");
  const [timeStep, setTimeStep] = useState("1");

  // Steady fields
  const [rtol, setRtol] = useState("1e-9");
  const [atol, setAtol] = useState("1e-15");
  const [maxSteps, setMaxSteps] = useState("10000");

  // Sync local state when the loaded config changes (auto-load)
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

  // When mode is toggled, reset kind to the first option for the new mode
  const handleModeChange = useCallback(
    (newMode: SolverMode) => {
      setMode(newMode);
      const newKind = newMode === "steady" ? STEADY_KINDS[0] : TRANSIENT_KINDS[0];
      setKind(newKind);
      // Persist into configStore so YAML editor reflects change
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

      {/* Mode toggle */}
      <div
        data-testid="solver-mode-toggle"
        className="flex rounded-md overflow-hidden border border-border text-xs font-medium"
      >
        <button
          data-testid="mode-steady"
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

      {/* Kind dropdown */}
      <label className="block text-xs text-muted-foreground">
        Kind
        <select
          data-testid="solver-kind-select"
          value={kind}
          onChange={(e) => handleKindChange(e.target.value as SolverKind)}
          className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
        >
          {kinds.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>
      </label>

      {/* Steady-state fields */}
      {mode === "steady" && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-xs text-muted-foreground">
              rtol
              <input
                data-testid="steady-rtol"
                type="text"
                value={rtol}
                onChange={(e) => setRtol(e.target.value)}
                className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
              />
            </label>
            <label className="block text-xs text-muted-foreground">
              atol
              <input
                data-testid="steady-atol"
                type="text"
                value={atol}
                onChange={(e) => setAtol(e.target.value)}
                className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
              />
            </label>
          </div>
          <label className="block text-xs text-muted-foreground">
            max_steps
            <input
              data-testid="steady-max-steps"
              type="number"
              value={maxSteps}
              onChange={(e) => setMaxSteps(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
              min="1"
            />
          </label>
        </div>
      )}

      {/* Transient fields */}
      {mode === "transient" && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-xs text-muted-foreground">
              Time (s)
              <input
                data-testid="transient-time"
                type="number"
                value={simTime}
                onChange={(e) => setSimTime(e.target.value)}
                className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
                min="0.1"
                step="0.1"
              />
            </label>
            <label className="block text-xs text-muted-foreground">
              Step (s)
              <input
                data-testid="transient-step"
                type="number"
                value={timeStep}
                onChange={(e) => setTimeStep(e.target.value)}
                className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
                min="0.001"
                step="0.001"
              />
            </label>
          </div>
        </div>
      )}

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
