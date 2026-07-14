import { useCallback, useMemo } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useAddEntityModalStore } from "@/stores/addEntityModalStore";
import { useSolverStore } from "@/stores/solverStore";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { SolverDetailsModal } from "./SolverDetailsModal";
import {
  KIND_LABELS,
  KIND_TO_MODE,
  STEADY_KINDS,
  TRANSIENT_KINDS,
  type SolverKind,
  type SolverMode,
} from "./solverShared";

interface Props {
  stageId: string;
}

/**
 * Shown in place of the properties panel when a stage (Cytoscape compound
 * group box) is selected — or by default when nothing else is selected and
 * the config only has one stage (see PropertiesPanel). Lets you add
 * reactors/connections directly into this stage and edit the solver that
 * applies to it.
 *
 * Boulder's solver settings (config.settings.solver) are a single global
 * setting, not truly per-stage — see the hasStageOverride banner in
 * SolverDetailsModal for configs whose YAML does override it per stage.
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
  const mode = useSolverStore((s) => s.mode);
  const setMode = useSolverStore((s) => s.setMode);
  const kind = useSolverStore((s) => s.kind);
  const setKind = useSolverStore((s) => s.setKind);
  const rtol = useSolverStore((s) => s.rtol);
  const setRtol = useSolverStore((s) => s.setRtol);
  const atol = useSolverStore((s) => s.atol);
  const setAtol = useSolverStore((s) => s.setAtol);
  const maxSteps = useSolverStore((s) => s.maxSteps);
  const setMaxSteps = useSolverStore((s) => s.setMaxSteps);
  const simTime = useSolverStore((s) => s.simTime);
  const setSimTime = useSolverStore((s) => s.setSimTime);
  const timeStep = useSolverStore((s) => s.timeStep);
  const setTimeStep = useSolverStore((s) => s.setTimeStep);

  const childNodes = useMemo(
    () => nodes.filter((n) => n.group === stageId),
    [nodes, stageId],
  );

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
    [config, fileName, setConfig, setMode, setKind],
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
    [config, fileName, setConfig, setKind],
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
    setDetailsOpen(false);
  }, [config, fileName, rtol, atol, maxSteps, mode, simTime, timeStep, setConfig, setDetailsOpen]);

  // True when the config has more than one stage. The backend always
  // materializes a groups.<stage>.solver block (even for a single implicit
  // stage — checking for its mere presence is always true and was the bug
  // behind this banner showing for every config, not just genuine
  // multi-stage overrides). With 2+ stages, this card's single global
  // toggle can't represent every stage's actual solver, so the warning is
  // meaningful; with exactly one stage there is nothing to override.
  const hasStageOverride = useMemo(() => {
    const groups = (config as unknown as Record<string, unknown>).groups as
      | Record<string, unknown>
      | undefined;
    return Object.keys(groups ?? {}).length > 1;
  }, [config]);

  const kinds = mode === "steady" ? STEADY_KINDS : TRANSIENT_KINDS;

  // This stage's own resolved solver, as Boulder actually runs it — distinct
  // from `kind` above, which is the global default the toggle below edits.
  // Boulder fully supports per-stage solver overrides (a YAML stage can set
  // its own solver: block; different stages can even mix steady and
  // transient in one run — see tests/test_stone_v2_fixtures.py); the GUI
  // just doesn't yet have an editor for that override, only the default
  // every stage without one falls back to.
  const stageOwnKind = useMemo(() => {
    const groups = (config as unknown as Record<string, unknown>).groups as
      | Record<string, { solver?: { kind?: string } }>
      | undefined;
    return groups?.[stageId]?.solver?.kind as SolverKind | undefined;
  }, [config, stageId]);
  const stageHasOwnOverride = Boolean(stageOwnKind) && stageOwnKind !== kind;

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

        {stageHasOwnOverride && stageOwnKind && (
          <p data-testid="stage-own-kind-note" className="text-xs text-amber-600 dark:text-amber-400">
            This stage's YAML sets its own solver:{" "}
            <span className="font-mono">{KIND_LABELS[stageOwnKind]}</span>. The toggle
            below edits the network's default, which this stage doesn't use.
          </p>
        )}

        <div className="flex items-center gap-2">
          <p
            className="text-xs text-muted-foreground truncate flex-1 min-w-0"
            title={KIND_LABELS[kind]}
          >
            {KIND_LABELS[kind]}
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
    </div>
  );
}
