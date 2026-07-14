/**
 * Asserts StageCard: lists the stage's child nodes, opens Add Reactor/Add
 * Connection pre-filled with this stage, and owns the Steady/Transient
 * toggle + Solver Details modal (moved here from SimulateCard).
 *
 * Also covers per-stage solver editing: a multi-stage config's toggle/kind/
 * details edits must persist into config.groups[stageId].solver (that
 * stage's own YAML block), not the network-wide config.settings.solver —
 * while a single-stage config still edits the network default, since
 * there's only one implicit stage and no per-stage YAML block to target.
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

const TWO_STAGE_GROUPS = {
  torch_stage: { stage_order: 1, mechanism: "gri30.yaml", solver: { kind: "advance_to_steady_state" } },
  psr_stage: { stage_order: 2, mechanism: "gri30.yaml", solver: { kind: "advance_to_steady_state" } },
};

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

  it("shows the current global solver kind and Steady/Transient toggle for a single-stage config", () => {
    render(<StageCard stageId="torch_stage" />);
    expect(screen.getByText("advance_to_steady_state")).toBeInTheDocument();
    expect(screen.getByTestId("mode-steady")).toBeInTheDocument();
    expect(screen.getByTestId("mode-transient")).toBeInTheDocument();
  });

  describe("single-stage config (no groups, or only one group)", () => {
    it("switching to Transient persists the new mode/kind into config.settings.solver", () => {
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

    it('Solver Details "Done" in transient mode persists grid.stop and grid.dt into config.settings.solver', () => {
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

    it("a single materialized group (e.g. 'default') still edits config.settings.solver, not config.groups", () => {
      const groups = {
        default: { stage_order: 1, mechanism: "gri30.yaml", solver: { kind: "advance_to_steady_state" } },
      };
      mockConfig = { ...mockConfig, groups };
      render(<StageCard stageId="default" />);
      fireEvent.click(screen.getByTestId("mode-transient"));
      const [updatedConfig] = mockSetConfig.mock.calls[0];
      // The single stage's own group block is left untouched by the edit.
      expect(updatedConfig.groups).toEqual(groups);
      expect(
        (updatedConfig.settings as Record<string, unknown>).solver,
      ).toEqual(expect.objectContaining({ mode: "transient" }));
    });
  });

  describe("multi-stage config (more than one group)", () => {
    it("displays this stage's own kind, not another stage's", () => {
      mockConfig = {
        ...mockConfig,
        groups: {
          torch_stage: { stage_order: 1, mechanism: "gri30.yaml", solver: { kind: "advance_grid", mode: "transient" } },
          psr_stage: { stage_order: 2, mechanism: "gri30.yaml", solver: { kind: "advance_to_steady_state", mode: "steady" } },
        },
      };
      render(<StageCard stageId="torch_stage" />);
      expect(screen.getByText("advance_grid")).toBeInTheDocument();
    });

    it("switching to Transient persists into config.groups[stageId].solver, leaving other stages untouched", () => {
      mockConfig = { ...mockConfig, groups: TWO_STAGE_GROUPS };
      render(<StageCard stageId="torch_stage" />);
      fireEvent.click(screen.getByTestId("mode-transient"));
      expect(mockSetConfig).toHaveBeenCalledOnce();
      const [updatedConfig] = mockSetConfig.mock.calls[0];
      const groups = updatedConfig.groups as Record<string, { solver: Record<string, unknown> }>;
      expect(groups.torch_stage.solver).toEqual(expect.objectContaining({ mode: "transient" }));
      expect(groups.psr_stage.solver).toEqual({ kind: "advance_to_steady_state" });
      // The network-wide default must be untouched by a per-stage edit.
      expect(updatedConfig.settings).toEqual(mockConfig.settings);
    });

    it("changing kind persists into this stage's own solver block only", () => {
      mockConfig = { ...mockConfig, groups: TWO_STAGE_GROUPS };
      render(<StageCard stageId="psr_stage" />);
      openSolverDetails();
      fireEvent.change(screen.getByTestId("solver-kind-select"), {
        target: { value: "solve_steady" },
      });
      expect(mockSetConfig).toHaveBeenCalledOnce();
      const [updatedConfig] = mockSetConfig.mock.calls[0];
      const groups = updatedConfig.groups as Record<string, { solver: Record<string, unknown> }>;
      expect(groups.psr_stage.solver).toEqual(expect.objectContaining({ kind: "solve_steady" }));
      expect(groups.torch_stage.solver).toEqual({ kind: "advance_to_steady_state" });
    });

    it('Solver Details "Done" persists rtol/atol/max_steps into config.groups[stageId].solver', () => {
      mockConfig = { ...mockConfig, groups: TWO_STAGE_GROUPS };
      render(<StageCard stageId="psr_stage" />);
      openSolverDetails();
      fireEvent.change(screen.getByTestId("steady-rtol"), { target: { value: "1e-10" } });
      fireEvent.change(screen.getByTestId("steady-atol"), { target: { value: "1e-16" } });
      fireEvent.change(screen.getByTestId("steady-max-steps"), { target: { value: "5000" } });
      mockSetConfig.mockClear();
      closeSolverDetailsDone();
      expect(mockSetConfig).toHaveBeenCalledOnce();
      const [updatedConfig] = mockSetConfig.mock.calls[0];
      const groups = updatedConfig.groups as Record<string, { solver: Record<string, unknown> }>;
      expect(groups.psr_stage.solver.rtol).toBeCloseTo(1e-10);
      expect(groups.psr_stage.solver.atol).toBeCloseTo(1e-16);
      expect(groups.psr_stage.solver.max_steps).toBe(5000);
      expect(groups.torch_stage.solver).toEqual({ kind: "advance_to_steady_state" });
      expect(updatedConfig.settings).toEqual(mockConfig.settings);
    });

    it("switching the selected stage re-syncs the displayed kind from that stage's own solver", () => {
      mockConfig = {
        ...mockConfig,
        groups: {
          torch_stage: { stage_order: 1, mechanism: "gri30.yaml", solver: { kind: "advance_grid", mode: "transient" } },
          psr_stage: { stage_order: 2, mechanism: "gri30.yaml", solver: { kind: "solve_steady", mode: "steady" } },
        },
      };
      const { rerender } = render(<StageCard stageId="torch_stage" />);
      expect(screen.getByText("advance_grid")).toBeInTheDocument();
      rerender(<StageCard stageId="psr_stage" />);
      expect(screen.getByText("solve_steady")).toBeInTheDocument();
    });
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
});
