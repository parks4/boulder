/**
 * Vitest unit tests for SimulateCard (Phase 0).
 *
 * Asserts:
 * - Default render shows Steady mode; steady-specific fields appear after opening Solver details.
 * - Clicking Transient toggle switches mode; transient fields appear in the modal after opening it.
 * - Kind dropdown in the modal respects steady vs transient mode.
 * - When config.settings.solver.kind is "advance_grid", the component initialises in transient mode.
 * - When config.settings.solver.mode is "transient", the component initialises in transient mode.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SimulateCard } from "./SimulateCard";

// ---------------------------------------------------------------------------
// Mock dependencies that reach out to the network or zustand stores
// ---------------------------------------------------------------------------

vi.mock("@/api/simulations", () => ({
  startSimulation: vi.fn().mockResolvedValue({ simulation_id: "test-123" }),
}));

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
});
