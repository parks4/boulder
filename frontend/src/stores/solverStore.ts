import { create } from "zustand";
import { deriveMode, KIND_TO_MODE, type SolverKind, type SolverMode } from "@/components/panels/solverShared";

interface SolverState {
  detailsOpen: boolean;
  setDetailsOpen: (open: boolean) => void;

  mode: SolverMode;
  kind: SolverKind;
  rtol: string;
  atol: string;
  maxSteps: string;
  simTime: string;
  timeStep: string;

  setMode: (mode: SolverMode) => void;
  setKind: (kind: SolverKind) => void;
  setRtol: (v: string) => void;
  setAtol: (v: string) => void;
  setMaxSteps: (v: string) => void;
  setSimTime: (v: string) => void;
  setTimeStep: (v: string) => void;

  /** Re-derive mode/kind/rtol/atol/maxSteps from a freshly loaded config.settings. */
  syncFromConfig: (settings: unknown) => void;
}

/**
 * Solver mode/kind/tolerances editing state for the network-wide default
 * (config.settings.solver).
 *
 * Edited from the Stage panel (StageCard) for single-stage configs, read by
 * SimulateCard's Run Simulation button (mode/simTime/timeStep decide
 * whether — and how — a transient run is issued). A shared store rather
 * than either component owning it, since both need it and neither is a
 * parent of the other.
 *
 * Multi-stage configs edit each stage's own solver override
 * (config.groups[stageId].solver) via local state in StageCard instead —
 * this store isn't used for that case.
 */
export const useSolverStore = create<SolverState>((set, get) => ({
  detailsOpen: false,
  setDetailsOpen: (open) => set({ detailsOpen: open }),

  mode: "steady",
  kind: "advance_to_steady_state",
  rtol: "1e-9",
  atol: "1e-15",
  maxSteps: "10000",
  simTime: "10",
  timeStep: "1",

  setMode: (mode) => set({ mode }),
  setKind: (kind) => set({ kind }),
  setRtol: (rtol) => set({ rtol }),
  setAtol: (atol) => set({ atol }),
  setMaxSteps: (maxSteps) => set({ maxSteps }),
  setSimTime: (simTime) => set({ simTime }),
  setTimeStep: (timeStep) => set({ timeStep }),

  syncFromConfig: (settings) => {
    const solver = (settings as Record<string, unknown> | null | undefined)?.solver as
      | Record<string, unknown>
      | undefined;
    const k = solver?.kind as string | undefined;
    const m = solver?.mode as SolverMode | undefined;
    const state = get();
    set({
      mode: m ?? deriveMode(k),
      kind: k && k in KIND_TO_MODE ? (k as SolverKind) : state.kind,
      rtol: solver?.rtol != null ? String(solver.rtol) : state.rtol,
      atol: solver?.atol != null ? String(solver.atol) : state.atol,
      maxSteps: solver?.max_steps != null ? String(solver.max_steps) : state.maxSteps,
    });
  },
}));
