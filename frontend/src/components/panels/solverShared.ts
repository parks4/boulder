export type SolverMode = "steady" | "transient";

export type SteadyKind = "advance_to_steady_state" | "solve_steady";
export type TransientKind = "advance" | "advance_grid" | "micro_step";
export type SolverKind = SteadyKind | TransientKind;

export const STEADY_KINDS: SteadyKind[] = ["advance_to_steady_state", "solve_steady"];
export const TRANSIENT_KINDS: TransientKind[] = ["advance", "advance_grid", "micro_step"];

export const KIND_LABELS: Record<SolverKind, string> = {
  advance_to_steady_state: "advance_to_steady_state",
  solve_steady: "solve_steady",
  advance: "advance",
  advance_grid: "advance_grid",
  micro_step: "micro_step",
};

export const KIND_TO_MODE: Record<SolverKind, SolverMode> = {
  advance_to_steady_state: "steady",
  solve_steady: "steady",
  advance: "transient",
  advance_grid: "transient",
  micro_step: "transient",
};

export function deriveMode(kind: string | undefined): SolverMode {
  if (!kind) return "steady";
  return KIND_TO_MODE[kind as SolverKind] ?? "steady";
}
