export type SolverMode = "steady" | "transient";

export type SteadyKind = "advance_to_steady_state" | "solve_steady";
export type TransientKind = "advance" | "advance_grid" | "micro_step";
export type SolverKind = SteadyKind | TransientKind;

export const STEADY_KINDS: SteadyKind[] = ["advance_to_steady_state", "solve_steady"];
export const TRANSIENT_KINDS: TransientKind[] = ["advance", "advance_grid", "micro_step"];

export const KIND_TO_MODE: Record<SolverKind, SolverMode> = {
  advance_to_steady_state: "steady",
  solve_steady: "steady",
  advance: "transient",
  advance_grid: "transient",
  micro_step: "transient",
};

const _ZERODIM = "https://cantera.org/stable/python/zerodim.html";

/**
 * Cantera doc link + description for each solver kind. Kept in sync with the
 * network-gated check in
 * tests/test_doc_links.py (Python has no visibility into this TS module, so
 * that test duplicates these URLs as literals).
 */
export const KIND_DOC_URLS: Record<SolverKind, { docUrl: string; description: string }> = {
  advance_to_steady_state: {
    docUrl: `${_ZERODIM}#cantera.ReactorNet.advance_to_steady_state`,
    description: "Integrates in time until the state stops changing (steady state).",
  },
  solve_steady: {
    docUrl: `${_ZERODIM}#cantera.ReactorNet.solve_steady`,
    description:
      "Solves directly for the steady-state solution — usually faster than time-marching to it.",
  },
  advance: {
    docUrl: `${_ZERODIM}#cantera.ReactorNet.advance`,
    description: "Integrates from the current time to a specified time.",
  },
  advance_grid: {
    docUrl: `${_ZERODIM}#cantera.ReactorNet.advance`,
    description: "Calls advance() once per point on the configured time grid.",
  },
  micro_step: {
    docUrl: `${_ZERODIM}#cantera.ReactorNet.advance`,
    description: "Calls advance() in small chunks, optionally reinitializing between them.",
  },
};

/**
 * Derive the solver mode from an explicit mode string (takes precedence) or
 * fall back to the kind-based lookup.  Returns "steady" when neither is set.
 */
export function deriveMode(
  kind: string | undefined,
  explicitMode?: string | undefined,
): SolverMode {
  if (explicitMode === "steady" || explicitMode === "transient") return explicitMode;
  if (!kind) return "steady";
  return KIND_TO_MODE[kind as SolverKind] ?? "steady";
}
