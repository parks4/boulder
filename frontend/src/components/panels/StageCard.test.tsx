/**
 * Asserts StageCard: lists the stage's child nodes, opens Add Reactor/Add
 * Connection pre-filled with this stage, and owns the Steady/Transient
 * toggle + Solver Details modal (moved here from SimulateCard — solver
 * settings are global, not per-stage, but are now edited from whichever
 * stage panel is open).
 *
 * Also covers what used to be SimulateCard's solver-editing tests: kind
 * dropdown filtering by mode, Solver Details "Done" persisting
 * rtol/atol/max_steps/grid, and the stage-override banner.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { StageCard } from "./StageCard";
import { useSolverStore } from "@/stores/solverStore";

const mockSetConfig = vi.fn();
let mockConfig: Record<string, unknown> = {
  nodes: [
    { id: "torch", type: "PlasmaTorchInstantaneousHeating", group: "torch_stage", properties: {} },
    { id: "psr", type: "IdealGasReactor", group: "psr_stage", properties: {} },
  ],
  connections: [],
  settings: { solver: { kind: "advance_to_steady_state" } },
};

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({ config: mockConfig, setConfig: mockSetConfig, fileName: "test.yaml" }),
}));

const mockOpenAddReactor = vi.fn();
const mockOpenAddConnection = vi.fn();
vi.mock("@/stores/addEntityModalStore", () => ({
  useAddEntityModalStore: (selector: (s: unknown) => unknown) =>
    selector({
      openAddReactor: mockOpenAddReactor,
      openAddConnection: mockOpenAddConnection,
    }),
}));

function openSolverDetails() {
  fireEvent.click(screen.getByText("Solver details..."));
}

function closeSolverDetailsDone() {
  fireEvent.click(screen.getByRole("button", { name: /done/i }));
}

describe("StageCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig = {
      nodes: [
        { id: "torch", type: "PlasmaTorchInstantaneousHeating", group: "torch_stage", properties: {} },
        { id: "psr", type: "IdealGasReactor", group: "psr_stage", properties: {} },
      ],
      connections: [],
      settings: { solver: { kind: "advance_to_steady_state" } },
    };
    useSolverStore.setState({
      detailsOpen: false,
      mode: "steady",
      kind: "advance_to_steady_state",
      rtol: "1e-9",
      atol: "1e-15",
      maxSteps: "10000",
      simTime: "10",
      timeStep: "1",
    });
  });

  it("lists only the child nodes belonging to this stage", () => {
    render(<StageCard stageId="torch_stage" />);
    expect(screen.getByText("torch")).toBeInTheDocument();
    expect(screen.queryByText("psr")).not.toBeInTheDocument();
  });

  it("shows a placeholder when the stage has no child nodes", () => {
    render(<StageCard stageId="empty_stage" />);
    expect(screen.getByText("No child nodes")).toBeInTheDocument();
  });

  it("opens Add Reactor pre-filled with this stage", () => {
    render(<StageCard stageId="torch_stage" />);
    fireEvent.click(screen.getByText("+ Add Reactor"));
    expect(mockOpenAddReactor).toHaveBeenCalledWith({ group: "torch_stage" });
  });

  it("opens Add Connection pre-filled with this stage", () => {
    render(<StageCard stageId="torch_stage" />);
    fireEvent.click(screen.getByText("+ Add Connection"));
    expect(mockOpenAddConnection).toHaveBeenCalledWith({ group: "torch_stage" });
  });

  it("shows the current global solver kind and Steady/Transient toggle", () => {
    render(<StageCard stageId="torch_stage" />);
    expect(screen.getByText("advance_to_steady_state")).toBeInTheDocument();
    expect(screen.getByTestId("mode-steady")).toBeInTheDocument();
    expect(screen.getByTestId("mode-transient")).toBeInTheDocument();
  });

  it("switching to Transient persists the new mode/kind via setConfig", () => {
    render(<StageCard stageId="torch_stage" />);
    fireEvent.click(screen.getByTestId("mode-transient"));
    expect(mockSetConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        settings: expect.objectContaining({
          solver: expect.objectContaining({ mode: "transient" }),
        }),
      }),
      "test.yaml",
    );
  });

  it("opens the Solver Details modal", () => {
    render(<StageCard stageId="torch_stage" />);
    openSolverDetails();
    expect(screen.getByTestId("solver-details-modal")).toBeInTheDocument();
  });

  it("kind dropdown only shows steady kinds in steady mode", () => {
    render(<StageCard stageId="torch_stage" />);
    openSolverDetails();
    const select = screen.getByTestId("solver-kind-select") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("advance_to_steady_state");
    expect(options).toContain("solve_steady");
    expect(options).not.toContain("advance_grid");
  });

  it("kind dropdown only shows transient kinds in transient mode", () => {
    useSolverStore.setState({ mode: "transient", kind: "advance" });
    render(<StageCard stageId="torch_stage" />);
    openSolverDetails();
    const select = screen.getByTestId("solver-kind-select") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("advance_grid");
    expect(options).toContain("micro_step");
    expect(options).not.toContain("advance_to_steady_state");
  });

  it('Solver Details "Done" persists rtol/atol/max_steps into config.settings.solver', () => {
    render(<StageCard stageId="torch_stage" />);
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

  it('Solver Details "Done" in transient mode persists grid.stop and grid.dt', () => {
    useSolverStore.setState({ mode: "transient", kind: "advance_grid" });
    render(<StageCard stageId="torch_stage" />);
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

  it("stage-override banner appears when the config has more than one stage", () => {
    mockConfig = {
      ...mockConfig,
      groups: {
        torch_stage: { stage_order: 1, mechanism: "gri30.yaml", solver: { kind: "solve_steady" } },
        psr_stage: { stage_order: 2, mechanism: "gri30.yaml", solver: { kind: "solve_steady" } },
      },
    };
    render(<StageCard stageId="torch_stage" />);
    openSolverDetails();
    expect(screen.getByTestId("stage-override-banner")).toBeInTheDocument();
  });

  it("stage-override banner is absent for a single-stage config, even though the backend always materializes that one stage's solver block", () => {
    mockConfig = {
      ...mockConfig,
      groups: {
        default: { stage_order: 1, mechanism: "gri30.yaml", solver: { kind: "advance_to_steady_state" } },
      },
    };
    render(<StageCard stageId="default" />);
    openSolverDetails();
    expect(screen.queryByTestId("stage-override-banner")).not.toBeInTheDocument();
  });

  it("stage-override banner is absent when config has no groups at all", () => {
    render(<StageCard stageId="torch_stage" />);
    openSolverDetails();
    expect(screen.queryByTestId("stage-override-banner")).not.toBeInTheDocument();
  });
});
