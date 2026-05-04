/**
 * Vitest unit tests for SimulateCard (Phase 0).
 *
 * Asserts:
 * - Default render shows Steady mode; steady-specific fields appear after opening Solver details.
 * - Clicking Transient toggle switches mode; transient fields appear in the modal after opening it.
 * - Kind dropdown in the modal respects steady vs transient mode.
 * - When config.settings.solver.kind is "advance_grid", the component initialises in transient mode.
 * - When config.settings.solver.mode is "transient", the component initialises in transient mode.
 * - Closing the modal via Done persists rtol/atol/max_steps into config.settings.solver (Fix C).
 * - In transient mode, Done also persists grid.stop and grid.dt (Fix D).
 * - Stage-override banner appears when config.groups contains per-stage solver blocks (Fix A).
 * - startSimulation is called without simulation_time/time_step in steady mode (Fix B).
 * - startSimulation is called with simulation_time/time_step in transient mode (Fix B).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SimulateCard } from "./SimulateCard";

// ---------------------------------------------------------------------------
// Mock dependencies that reach out to the network or zustand stores
// ---------------------------------------------------------------------------

import { startSimulation } from "@/api/simulations";

vi.mock("@/api/simulations", () => ({
  startSimulation: vi.fn().mockResolvedValue({ simulation_id: "test-123" }),
}));

const mockStartSimulation = startSimulation as ReturnType<typeof vi.fn>;

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const mockSetConfig = vi.fn();
let mockConfig: Record<string, unknown> = { nodes: [], connections: [] };

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) => {
    const store = {
      config: mockConfig,
      fileName: "test.yaml",
      setConfig: mockSetConfig,
    };
    return selector(store);
  },
}));

vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: () => ({
    isRunning: false,
    simulationId: null,
    pythonCode: "",
    beginSimulationRun: vi.fn(),
    startSimulation: vi.fn(),
    setError: vi.fn(),
  }),
}));

function openSolverDetails() {
  fireEvent.click(screen.getByTestId("open-solver-details"));
}

function closeSolverDetailsDone() {
  fireEvent.click(screen.getByRole("button", { name: /done/i }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SimulateCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig = { nodes: [], connections: [] };
  });

  it("renders in steady mode by default (no solver config)", () => {
    render(<SimulateCard />);
    expect(screen.getByTestId("mode-steady")).toBeInTheDocument();
    expect(screen.getByTestId("mode-transient")).toBeInTheDocument();
    openSolverDetails();
    expect(screen.getByTestId("steady-rtol")).toBeInTheDocument();
    expect(screen.getByTestId("steady-atol")).toBeInTheDocument();
    expect(screen.getByTestId("steady-max-steps")).toBeInTheDocument();
    expect(screen.queryByTestId("transient-time")).not.toBeInTheDocument();
    expect(screen.queryByTestId("transient-step")).not.toBeInTheDocument();
  });

  it("clicking Transient toggle shows transient fields in modal and hides steady fields", () => {
    render(<SimulateCard />);
    fireEvent.click(screen.getByTestId("mode-transient"));
    openSolverDetails();
    expect(screen.getByTestId("transient-time")).toBeInTheDocument();
    expect(screen.getByTestId("transient-step")).toBeInTheDocument();
    expect(screen.queryByTestId("steady-rtol")).not.toBeInTheDocument();
  });

  it("toggling back to Steady re-shows steady fields in modal", () => {
    render(<SimulateCard />);
    fireEvent.click(screen.getByTestId("mode-transient"));
    fireEvent.click(screen.getByTestId("mode-steady"));
    openSolverDetails();
    expect(screen.getByTestId("steady-rtol")).toBeInTheDocument();
    expect(screen.queryByTestId("transient-time")).not.toBeInTheDocument();
  });

  it("calls setConfig when mode toggle is clicked", () => {
    render(<SimulateCard />);
    fireEvent.click(screen.getByTestId("mode-transient"));
    expect(mockSetConfig).toHaveBeenCalledOnce();
    const [updatedConfig] = mockSetConfig.mock.calls[0];
    const solver = (updatedConfig.settings as Record<string, unknown>)
      .solver as Record<string, unknown>;
    expect(solver.mode).toBe("transient");
  });

  it("kind dropdown only shows steady kinds in steady mode", () => {
    render(<SimulateCard />);
    openSolverDetails();
    const select = screen.getByTestId("solver-kind-select") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("advance_to_steady_state");
    expect(options).toContain("solve_steady");
    expect(options).not.toContain("advance_grid");
    expect(options).not.toContain("micro_step");
  });

  it("kind dropdown only shows transient kinds in transient mode", () => {
    render(<SimulateCard />);
    fireEvent.click(screen.getByTestId("mode-transient"));
    openSolverDetails();
    const select = screen.getByTestId("solver-kind-select") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("advance");
    expect(options).toContain("advance_grid");
    expect(options).toContain("micro_step");
    expect(options).not.toContain("advance_to_steady_state");
  });

  it("initialises in transient mode when config.settings.solver.kind is advance_grid", () => {
    mockConfig = {
      nodes: [],
      connections: [],
      settings: { solver: { kind: "advance_grid" } },
    };
    render(<SimulateCard />);
    openSolverDetails();
    expect(screen.getByTestId("transient-time")).toBeInTheDocument();
    expect(screen.queryByTestId("steady-rtol")).not.toBeInTheDocument();
  });

  it("initialises in transient mode when config.settings.solver.mode is transient", () => {
    mockConfig = {
      nodes: [],
      connections: [],
      settings: { solver: { mode: "transient", kind: "micro_step" } },
    };
    render(<SimulateCard />);
    openSolverDetails();
    expect(screen.getByTestId("transient-time")).toBeInTheDocument();
  });

  it("changing kind in dropdown calls setConfig with updated kind", () => {
    render(<SimulateCard />);
    openSolverDetails();
    const select = screen.getByTestId("solver-kind-select");
    fireEvent.change(select, { target: { value: "solve_steady" } });
    expect(mockSetConfig).toHaveBeenCalledOnce();
    const [updatedConfig] = mockSetConfig.mock.calls[0];
    const solver = (updatedConfig.settings as Record<string, unknown>)
      .solver as Record<string, unknown>;
    expect(solver.kind).toBe("solve_steady");
  });

  it("Done button persists rtol/atol/max_steps into config.settings.solver (Fix C)", () => {
    render(<SimulateCard />);
    openSolverDetails();
    fireEvent.change(screen.getByTestId("steady-rtol"), { target: { value: "1e-10" } });
    fireEvent.change(screen.getByTestId("steady-atol"), { target: { value: "1e-16" } });
    fireEvent.change(screen.getByTestId("steady-max-steps"), { target: { value: "5000" } });
    mockSetConfig.mockClear();
    closeSolverDetailsDone();
    expect(mockSetConfig).toHaveBeenCalledOnce();
    const [updatedConfig] = mockSetConfig.mock.calls[0];
    const solver = (updatedConfig.settings as Record<string, unknown>)
      .solver as Record<string, unknown>;
    expect(solver.rtol).toBeCloseTo(1e-10);
    expect(solver.atol).toBeCloseTo(1e-16);
    expect(solver.max_steps).toBe(5000);
  });

  it("Done button in transient mode persists grid.stop and grid.dt (Fix D)", () => {
    render(<SimulateCard />);
    fireEvent.click(screen.getByTestId("mode-transient"));
    openSolverDetails();
    fireEvent.change(screen.getByTestId("transient-time"), { target: { value: "20" } });
    fireEvent.change(screen.getByTestId("transient-step"), { target: { value: "0.5" } });
    mockSetConfig.mockClear();
    closeSolverDetailsDone();
    expect(mockSetConfig).toHaveBeenCalledOnce();
    const [updatedConfig] = mockSetConfig.mock.calls[0];
    const solver = (updatedConfig.settings as Record<string, unknown>)
      .solver as Record<string, unknown>;
    const grid = solver.grid as Record<string, unknown>;
    expect(grid.stop).toBeCloseTo(20);
    expect(grid.dt).toBeCloseTo(0.5);
  });

  it("stage-override banner appears when config.groups has per-stage solver blocks (Fix A)", () => {
    mockConfig = {
      nodes: [],
      connections: [],
      groups: {
        stage1: { stage_order: 1, mechanism: "gri30.yaml", solver: { kind: "solve_steady" } },
      },
    };
    render(<SimulateCard />);
    openSolverDetails();
    expect(screen.getByTestId("stage-override-banner")).toBeInTheDocument();
  });

  it("stage-override banner is absent when config has no groups (Fix A)", () => {
    render(<SimulateCard />);
    openSolverDetails();
    expect(screen.queryByTestId("stage-override-banner")).not.toBeInTheDocument();
  });

  it("Run button calls startSimulation without time/step in steady mode (Fix B)", async () => {
    mockConfig = { nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }], connections: [] };
    render(<SimulateCard />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run simulation/i }));
    });
    expect(mockStartSimulation).toHaveBeenCalledOnce();
    const [, simTime, timeStep] = mockStartSimulation.mock.calls[0];
    expect(simTime).toBeUndefined();
    expect(timeStep).toBeUndefined();
  });

  it("Run button calls startSimulation with time/step in transient mode (Fix B)", async () => {
    mockConfig = { nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }], connections: [] };
    render(<SimulateCard />);
    fireEvent.click(screen.getByTestId("mode-transient"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run simulation/i }));
    });
    expect(mockStartSimulation).toHaveBeenCalledOnce();
    const [, simTime, timeStep] = mockStartSimulation.mock.calls[0];
    expect(typeof simTime).toBe("number");
    expect(typeof timeStep).toBe("number");
  });
});
