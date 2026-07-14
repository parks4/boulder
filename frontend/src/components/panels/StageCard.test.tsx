/**
 * Asserts StageCard: lists the stage's child nodes, opens Add Reactor/Add
 * Connection pre-filled with this stage, and opens the shared Solver
 * Details modal (solver settings are global, not per-stage, so it reads
 * the same config.settings.solver SimulateCard edits).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { StageCard } from "./StageCard";

const mockConfig: Record<string, unknown> = {
  nodes: [
    { id: "torch", type: "PlasmaTorchInstantaneousHeating", group: "torch_stage", properties: {} },
    { id: "psr", type: "IdealGasReactor", group: "psr_stage", properties: {} },
  ],
  connections: [],
  settings: { solver: { kind: "advance_to_steady_state" } },
};

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({ config: mockConfig }),
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

const mockSetSolverDetailsOpen = vi.fn();
vi.mock("@/stores/solverDetailsStore", () => ({
  useSolverDetailsStore: (selector: (s: unknown) => unknown) =>
    selector({ setOpen: mockSetSolverDetailsOpen }),
}));

describe("StageCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("shows the current global solver kind and opens Solver details", () => {
    render(<StageCard stageId="torch_stage" />);
    expect(screen.getByText("advance_to_steady_state")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Solver details..."));
    expect(mockSetSolverDetailsOpen).toHaveBeenCalledWith(true);
  });
});
