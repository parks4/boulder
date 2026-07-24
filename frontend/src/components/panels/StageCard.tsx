import { useCallback, useMemo, useState } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useAddEntityModalStore } from "@/stores/addEntityModalStore";
import { useSolverStore } from "@/stores/solverStore";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { SolverDetailsModal } from "./SolverDetailsModal";
import {
  deriveMode,
  KIND_TO_MODE,
  STEADY_KINDS,
  TRANSIENT_KINDS,
  type SolverKind,
  type SolverMode,
} from "./solverShared";

interface Props {
  stageId: string;
}

function deriveLocalSolverState(solver: Record<string, unknown> | undefined) {
  const grid = solver?.grid as Record<string, unknown> | undefined;
  return {
    mode: (solver?.mode as SolverMode) ?? deriveMode(solver?.kind as string | undefined),
    kind: (solver?.kind as SolverKind) ?? "advance_to_steady_state",
    rtol: solver?.rtol != null ? String(solver.rtol) : "1e-9",
    atol: solver?.atol != null ? String(solver.atol) : "1e-15",
    maxSteps: solver?.max_steps != null ? String(solver.max_steps) : "10000",
    startTime: String(grid?.start ?? "0"),
    simTime: String(grid?.stop ?? solver?.advance_time ?? "10"),
    timeStep: String(grid?.dt ?? "1"),
  };
}

/**
 * Shown in place of the properties panel when a stage (Cytoscape compound
 * group box) is selected — or by default when nothing else is selected and
 * the config only has one stage (see PropertiesPanel). Lets you add
 * reactors/connections directly into this stage and edit the solver that
 * applies to it.
 *
 * Boulder supports genuine per-stage solver overrides: a stage's YAML can
 * set its own `solver:` block (config.groups[stageId].solver), distinct
 * from the network-wide default (config.settings.solver) a stage falls
 * back to when it has none. For a multi-stage config, this card edits that
 * stage's own override directly. For a single-stage config there's only
 * one implicit stage, so editing it IS editing the network default — the
 * shared solverStore (also read by SimulateCard's Run button) covers that
 * case.
 */
export function StageCard({ stageId }: Props) {
  const nodes = useConfigStore((s) => s.config.nodes);
  const config = useConfigStore((s) => s.config);
  const setConfig = useConfigStore((s) => s.setConfig);
  const fileName = useConfigStore((s) => s.fileName);
  const openAddReactor = useAddEntityModalStore((s) => s.openAddReactor);
  const openAddConnection = useAddEntityModalStore((s) => s.openAddConnection);

  const detailsOpen = useSolverStore((s) => s.detailsOpen);
  const setDetailsOpen = useSolverStore((s) => s.setDetailsOpen);
  const globalMode = useSolverStore((s) => s.mode);
  const globalKind = useSolverStore((s) => s.kind);
  const globalRtol = useSolverStore((s) => s.rtol);
  const globalAtol = useSolverStore((s) => s.atol);
  const globalMaxSteps = useSolverStore((s) => s.maxSteps);
  const globalStartTime = useSolverStore((s) => s.startTime);
  const globalSimTime = useSolverStore((s) => s.simTime);
  const globalTimeStep = useSolverStore((s) => s.timeStep);
  const setGlobalMode = useSolverStore((s) => s.setMode);
  const setGlobalKind = useSolverStore((s) => s.setKind);
  const setGlobalRtol = useSolverStore((s) => s.setRtol);
  const setGlobalAtol = useSolverStore((s) => s.setAtol);
  const setGlobalMaxSteps = useSolverStore((s) => s.setMaxSteps);
  const setGlobalStartTime = useSolverStore((s) => s.setStartTime);
  const setGlobalSimTime = useSolverStore((s) => s.setSimTime);
  const setGlobalTimeStep = useSolverStore((s) => s.setTimeStep);

  const isMultiStage = Object.keys(config.groups ?? {}).length > 1;

  const childNodes = useMemo(
    () => nodes.filter((n) => n.group === stageId),
    [nodes, stageId],
  );

  // --- Local, per-stage-scoped solver state (multi-stage configs only) ---
  const stageSolver = config.groups?.[stageId]?.solver;
  const [localState, setLocalState] = useState(() => deriveLocalSolverState(stageSolver));
  const { mode: localMode, kind: localKind, rtol: localRtol, atol: localAtol, maxSteps: localMaxSteps, startTime: localStartTime, simTime: localSimTime, timeStep: localTimeStep } = localState;
  const setLocalMode = (v: SolverMode) => setLocalState((s) => ({ ...s, mode: v }));
  const setLocalKind = (v: SolverKind) => setLocalState((s) => ({ ...s, kind: v }));
  const setLocalRtol = (v: string) => setLocalState((s) => ({ ...s, rtol: v }));
  const setLocalAtol = (v: string) => setLocalState((s) => ({ ...s, atol: v }));
  const setLocalMaxSteps = (v: string) => setLocalState((s) => ({ ...s, maxSteps: v }));
  const setLocalStartTime = (v: string) => setLocalState((s) => ({ ...s, startTime: v }));
  const setLocalSimTime = (v: string) => setLocalState((s) => ({ ...s, simTime: v }));
  const setLocalTimeStep = (v: string) => setLocalState((s) => ({ ...s, timeStep: v }));

  // Re-sync local per-stage state whenever the selected stage changes, e.g.
  // switching which stage's panel is open — following React's "adjust state
  // during render" pattern (not an effect) so this doesn't trigger an extra
  // commit. `fileName` is included so re-opening the same stage id in a
  // freshly-loaded config also re-syncs.
  const resetKey = `${fileName ?? ""}:${stageId}`;
  const [lastResetKey, setLastResetKey] = useState(resetKey);
  if (isMultiStage && resetKey !== lastResetKey) {
    setLastResetKey(resetKey);
    setLocalState(deriveLocalSolverState(stageSolver));
  }

  // Active values: whichever source (this stage's own override, or the
  // network default) this stage's panel is currently editing.
  const mode = isMultiStage ? localMode : globalMode;
  const kind = isMultiStage ? localKind : globalKind;
  const rtol = isMultiStage ? localRtol : globalRtol;
  const atol = isMultiStage ? localAtol : globalAtol;
  const maxSteps = isMultiStage ? localMaxSteps : globalMaxSteps;
  const startTime = isMultiStage ? localStartTime : globalStartTime;
  const simTime = isMultiStage ? localSimTime : globalSimTime;
  const timeStep = isMultiStage ? localTimeStep : globalTimeStep;
  const onRtolChange = isMultiStage ? setLocalRtol : setGlobalRtol;
  const onAtolChange = isMultiStage ? setLocalAtol : setGlobalAtol;
  const onMaxStepsChange = isMultiStage ? setLocalMaxSteps : setGlobalMaxSteps;
  const onStartTimeChange = isMultiStage ? setLocalStartTime : setGlobalStartTime;
  const onSimTimeChange = isMultiStage ? setLocalSimTime : setGlobalSimTime;
  const onTimeStepChange = isMultiStage ? setLocalTimeStep : setGlobalTimeStep;

  const handleModeChange = useCallback(
    (newMode: SolverMode) => {
      const newKind = newMode === "steady" ? STEADY_KINDS[0] : TRANSIENT_KINDS[0];
      if (isMultiStage) {
        setLocalMode(newMode);
        setLocalKind(newKind);
        const currentGroups = config.groups ?? {};
        const currentGroup = currentGroups[stageId] ?? {};
        const currentSolver = currentGroup.solver ?? {};
        setConfig(
          {
            ...config,
            groups: {
              ...currentGroups,
              [stageId]: {
                ...currentGroup,
                solver: { ...currentSolver, mode: newMode, kind: newKind },
              },
            },
          },
          fileName,
        );
        return;
      }
      setGlobalMode(newMode);
      setGlobalKind(newKind);
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
    [config, fileName, isMultiStage, stageId, setConfig, setGlobalMode, setGlobalKind],
  );

  const handleKindChange = useCallback(
    (newKind: SolverKind) => {
      const newMode = KIND_TO_MODE[newKind];
      if (isMultiStage) {
        setLocalKind(newKind);
        const currentGroups = config.groups ?? {};
        const currentGroup = currentGroups[stageId] ?? {};
        const currentSolver = currentGroup.solver ?? {};
        setConfig(
          {
            ...config,
            groups: {
              ...currentGroups,
              [stageId]: {
                ...currentGroup,
                solver: { ...currentSolver, mode: newMode, kind: newKind },
              },
            },
          },
          fileName,
        );
        return;
      }
      setGlobalKind(newKind);
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
    [config, fileName, isMultiStage, stageId, setConfig, setGlobalKind],
  );

  // Builds the transient-specific fields, merging into (not replacing) an
  // existing grid dict so unrelated keys (e.g. an explicit list grid, or a
  // `start` the modal doesn't have a field for on other kinds) survive.
  const buildTransientExtra = useCallback(
    (currentSolver: Record<string, unknown>): Record<string, unknown> => {
      if (mode !== "transient") return {};
      if (kind === "advance") return { advance_time: parseFloat(simTime) };
      if (kind === "advance_grid") {
        const currentGrid = currentSolver.grid;
        const gridBase =
          currentGrid && typeof currentGrid === "object" && !Array.isArray(currentGrid)
            ? (currentGrid as Record<string, unknown>)
            : {};
        return {
          grid: {
            ...gridBase,
            start: parseFloat(startTime),
            stop: parseFloat(simTime),
            dt: parseFloat(timeStep),
          },
        };
      }
      // micro_step isn't represented by this modal's fields (it uses
      // t_total/chunk_dt/max_dt, not grid.start/stop/dt) — leave it alone.
      return {};
    },
    [mode, kind, startTime, simTime, timeStep],
  );

  // Persists tolerance and transient-grid values from the modal into
  // whichever solver block this stage's panel is editing.
  const handleSolverDetailsDone = useCallback(() => {
    const rtolNum = parseFloat(rtol);
    const atolNum = parseFloat(atol);
    const maxStepsNum = parseInt(maxSteps, 10);
    const currentGroups = config.groups ?? {};
    const currentGroup = currentGroups[stageId] ?? {};
    const currentSettings = (config.settings as Record<string, unknown>) ?? {};
    const currentSolver = (isMultiStage
      ? (currentGroup.solver ?? {})
      : (currentSettings.solver ?? {})) as Record<string, unknown>;
    const extra: Record<string, unknown> = {
      ...(Number.isFinite(rtolNum) ? { rtol: rtolNum } : {}),
      ...(Number.isFinite(atolNum) ? { atol: atolNum } : {}),
      ...(Number.isFinite(maxStepsNum) ? { max_steps: maxStepsNum } : {}),
      ...buildTransientExtra(currentSolver),
    };
    if (isMultiStage) {
      setConfig(
        {
          ...config,
          groups: {
            ...currentGroups,
            [stageId]: { ...currentGroup, solver: { ...currentSolver, ...extra } },
          },
        },
        fileName,
      );
    } else {
      setConfig(
        {
          ...config,
          settings: { ...currentSettings, solver: { ...currentSolver, ...extra } },
        },
        fileName,
      );
    }
    setDetailsOpen(false);
  }, [
    config,
    fileName,
    rtol,
    atol,
    maxSteps,
    buildTransientExtra,
    isMultiStage,
    stageId,
    setConfig,
    setDetailsOpen,
  ]);

  // Dismiss without persisting — the ✕ button, backdrop click, and Escape
  // key should not silently commit whatever's in the (possibly-unedited)
  // fields back into the config.
  const handleSolverDetailsCancel = useCallback(() => {
    setDetailsOpen(false);
  }, [setDetailsOpen]);

  const kinds = mode === "steady" ? STEADY_KINDS : TRANSIENT_KINDS;

  return (
    <div id="stage-card" className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div>
        <h3 className="font-semibold text-sm text-foreground">{stageId}</h3>
        <span className="text-xs text-muted-foreground">Stage</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Button
          id="stage-add-reactor"
          onClick={() => openAddReactor({ group: stageId })}
          variant="muted"
          size="sm"
        >
          + Add Reactor
        </Button>
        <Button
          id="stage-add-connection"
          onClick={() => openAddConnection({ group: stageId })}
          variant="muted"
          size="sm"
        >
          + Add Connection
        </Button>
      </div>

      <div className="border-t border-border pt-2 mt-1">
        <p className="text-xs text-muted-foreground mb-1.5">Child nodes</p>
        <div className="divide-y divide-border">
          {childNodes.map((n) => (
            <div key={n.id} className="py-1 flex items-center justify-between gap-2">
              <span className="text-xs font-mono text-foreground">{n.id}</span>
              <span className="text-xs text-muted-foreground">{n.type}</span>
            </div>
          ))}
          {childNodes.length === 0 && (
            <p className="text-xs text-muted-foreground py-1 italic">No child nodes</p>
          )}
        </div>
      </div>

      <div className="border-t border-border pt-2 mt-1 space-y-2">
        <p className="text-xs text-muted-foreground">
          {isMultiStage ? "This stage's own solver" : "Solver"}
        </p>
        <div
          data-testid="solver-mode-toggle"
          className="flex rounded-md overflow-hidden border border-border text-xs font-medium"
        >
          <Tooltip
            className="flex-1"
            content="Solves for the network's steady-state: mass flows continuously enter and exit, and time-resolved plots track a gas parcel as it moves through the network."
          >
            <button
              data-testid="mode-steady"
              type="button"
              onClick={() => handleModeChange("steady")}
              className={`w-full py-1.5 transition-colors ${
                mode === "steady"
                  ? "bg-blue-600 text-white"
                  : "bg-input text-muted-foreground hover:bg-muted"
              }`}
            >
              Steady
            </button>
          </Tooltip>
          <Tooltip
            className="flex-1"
            content="Time-resolved simulation: plots show how the system evolves over the real timescale you configure below."
          >
            <button
              data-testid="mode-transient"
              type="button"
              onClick={() => handleModeChange("transient")}
              className={`w-full py-1.5 transition-colors ${
                mode === "transient"
                  ? "bg-teal-600 text-white"
                  : "bg-input text-muted-foreground hover:bg-muted"
              }`}
            >
              Transient
            </button>
          </Tooltip>
        </div>

        <div className="flex items-center gap-2">
          <p
            className="text-xs text-muted-foreground truncate flex-1 min-w-0"
            title={kind}
          >
            {kind}
          </p>
          <Button
            id="stage-solver-details"
            data-testid="open-solver-details"
            type="button"
            variant="secondary"
            size="sm"
            className="shrink-0"
            onClick={() => setDetailsOpen(true)}
          >
            Solver details...
          </Button>
        </div>
      </div>

      <SolverDetailsModal
        open={detailsOpen}
        onCancel={handleSolverDetailsCancel}
        onDone={handleSolverDetailsDone}
        mode={mode}
        kind={kind}
        kinds={kinds}
        onKindChange={handleKindChange}
        rtol={rtol}
        onRtolChange={onRtolChange}
        atol={atol}
        onAtolChange={onAtolChange}
        maxSteps={maxSteps}
        onMaxStepsChange={onMaxStepsChange}
        startTime={startTime}
        onStartTimeChange={onStartTimeChange}
        simTime={simTime}
        onSimTimeChange={onSimTimeChange}
        timeStep={timeStep}
        onTimeStepChange={onTimeStepChange}
      />
    </div>
  );
}
