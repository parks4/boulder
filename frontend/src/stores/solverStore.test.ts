import { describe, expect, it } from "vitest";
import { useSolverStore } from "./solverStore";

describe("solverStore.syncFromConfig time fields", () => {
  it("reads the nominal end_time and dt when the solver declares none", () => {
    useSolverStore.getState().syncFromConfig({
      end_time: 0.25,
      dt: 0.05,
      solver: { kind: "advance" },
    });
    const s = useSolverStore.getState();
    expect([s.simTime, s.timeStep]).toEqual(["0.25", "0.05"]);
  });

  it("prefers the solver's own advance_time and grid.dt", () => {
    useSolverStore.getState().syncFromConfig({
      end_time: 9,
      dt: 9,
      solver: { kind: "advance", advance_time: 2, grid: { dt: 0.5 } },
    });
    const s = useSolverStore.getState();
    expect([s.simTime, s.timeStep]).toEqual(["2", "0.5"]);
  });

  it("falls back to a tenth of the window when no step is declared", () => {
    useSolverStore.getState().syncFromConfig({
      solver: { kind: "advance", advance_time: 2 },
    });
    const s = useSolverStore.getState();
    expect([s.simTime, s.timeStep]).toEqual(["2", "0.2"]);
  });
});
