/**
 * Asserts ScenarioPane: the new rename action calls the store's
 * renameScenario, and the previously-missing onSaved wiring (both in the
 * empty "no scenarios yet" state and the populated one) triggers a refresh
 * after editing a scenario's YAML.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ScenarioPane } from "./ScenarioPane";

const mockRefresh = vi.fn();
const mockSetActive = vi.fn();
const mockRenameScenario = vi.fn();
const mockDeleteScenario = vi.fn();
let mockAvailable = true;
let mockScenarios: Array<{ id: string; label: string; t0_K: number }> = [
  { id: "A", label: "Scenario A", t0_K: 300 },
];
let mockAuthoredIds: string[] = [];

vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: () => ({
    available: mockAvailable,
    scenarios: mockScenarios,
    authoredIds: mockAuthoredIds,
    createdAt: undefined,
    activeId: null,
    loading: false,
    error: null,
    refresh: mockRefresh,
    setActive: mockSetActive,
    renameScenario: mockRenameScenario,
    deleteScenario: mockDeleteScenario,
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/modals/AddScenarioModal", () => ({
  AddScenarioModal: () => null,
}));

let capturedOnSaved: (() => void) | undefined;
vi.mock("@/components/modals/ScenarioYamlEditorModal", () => ({
  ScenarioYamlEditorModal: ({ onSaved }: { onSaved?: () => void }) => {
    capturedOnSaved = onSaved;
    return null;
  },
}));

vi.mock("./SweepResultsPlot", () => ({
  SweepResultsPlot: () => null,
}));

describe("ScenarioPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedOnSaved = undefined;
    mockAvailable = true;
    mockScenarios = [{ id: "A", label: "Scenario A", t0_K: 300 }];
    mockAuthoredIds = [];
  });

  it("renaming a scenario prompts for a new id and calls renameScenario", () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("A2");
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle("Rename scenario"));

    expect(promptSpy).toHaveBeenCalledWith('Rename scenario "A" to:', "A");
    expect(mockRenameScenario).toHaveBeenCalledWith("A", "A2");
    promptSpy.mockRestore();
  });

  it("rejects an invalid new id without calling renameScenario", () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("bad id!");
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle("Rename scenario"));

    expect(mockRenameScenario).not.toHaveBeenCalled();
    promptSpy.mockRestore();
  });

  it("does nothing when the rename prompt is cancelled or unchanged", () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("A");
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle("Rename scenario"));

    expect(mockRenameScenario).not.toHaveBeenCalled();
    promptSpy.mockRestore();
  });

  it("wires onSaved into the scoped editor in the populated state", () => {
    render(<ScenarioPane />);
    expect(capturedOnSaved).toBeInstanceOf(Function);
    capturedOnSaved?.();
    expect(mockRefresh).toHaveBeenCalled();
  });

  it("wires onSaved into the scoped editor in the empty (no scenarios yet) state too", () => {
    mockAvailable = false;
    mockScenarios = [];
    render(<ScenarioPane />);
    expect(capturedOnSaved).toBeInstanceOf(Function);
    capturedOnSaved?.();
    expect(mockRefresh).toHaveBeenCalled();
  });

  it("lists authored-but-not-yet-swept scenarios before any store exists", () => {
    mockAvailable = false;
    mockScenarios = [];
    mockAuthoredIds = ["draft_a", "draft_b"];
    render(<ScenarioPane />);

    expect(screen.getByText("draft_a")).toBeInTheDocument();
    expect(screen.getByText("draft_b")).toBeInTheDocument();
    expect(screen.getByText(/Run Sweep to solve them/)).toBeInTheDocument();
  });

  it("deleting an authored-but-unswept scenario confirms and calls deleteScenario", () => {
    mockAvailable = false;
    mockScenarios = [];
    mockAuthoredIds = ["draft_a"];
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle("Delete scenario"));

    expect(mockDeleteScenario).toHaveBeenCalledWith("draft_a");
    confirmSpy.mockRestore();
  });
});
