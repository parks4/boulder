/**
 * Asserts ScenarioPane: deleting a scenario confirms first, then reports
 * whether a cached result was purged too; "Regenerate cache" confirms, then
 * starts a no-cache sweep via the shared sweep-run store; and the
 * previously-missing onSaved wiring (both in the empty "no scenarios yet"
 * state and the populated one) triggers a refresh after editing a scenario's
 * YAML.
 *
 * No "Rename scenario" action here — a scenario's display name is
 * `metadata.scenario_name`, already editable via "Edit scenario YAML"; a
 * separate control that renames the underlying `scenario:` mapping key
 * would be a second, confusing way to change what looks like the same thing.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ScenarioPane } from "./ScenarioPane";

const mockRefresh = vi.fn();
const mockSetActive = vi.fn();
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
    deleteScenario: mockDeleteScenario,
  }),
}));

const mockRunSweepJob = vi.fn();
let mockSweeping = false;
vi.mock("@/stores/sweepStore", () => ({
  useSweepRunStore: (selector: (s: unknown) => unknown) =>
    selector({ sweeping: mockSweeping, run: mockRunSweepJob }),
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
    mockSweeping = false;
    mockAuthoredIds = [];
  });

  it("deleting a scenario confirms first, then calls deleteScenario", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockDeleteScenario.mockResolvedValue({ cachePurged: true });
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle("Delete scenario"));

    expect(confirmSpy).toHaveBeenCalledWith(
      'Delete scenario "A"? This also removes its cached trajectory ' +
        "immediately. This cannot be undone.",
    );
    expect(mockDeleteScenario).toHaveBeenCalledWith("A");
    confirmSpy.mockRestore();
  });

  it("does nothing when the delete confirmation is dismissed", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle("Delete scenario"));

    expect(mockDeleteScenario).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("Regenerate cache confirms, then starts a no-cache sweep", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle(/Regenerate cache/));

    expect(confirmSpy).toHaveBeenCalledWith(
      "Regenerate the cache? This re-solves every scenario in this sweep " +
        "from scratch, ignoring cached results. This may take a while.",
    );
    expect(mockRunSweepJob).toHaveBeenCalledWith({ total: 1, noCache: true });
    confirmSpy.mockRestore();
  });

  it("does nothing when the Regenerate cache confirmation is dismissed", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle(/Regenerate cache/));

    expect(mockRunSweepJob).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("disables Regenerate cache while a sweep is already running", () => {
    mockSweeping = true;
    render(<ScenarioPane />);

    expect(screen.getByTitle(/Regenerate cache/)).toBeDisabled();
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
