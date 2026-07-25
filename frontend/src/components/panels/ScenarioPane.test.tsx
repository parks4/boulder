/**
 * Asserts ScenarioPane: deleting a scenario confirms first, then reports
 * whether a cached result was purged too; "Clear cache" confirms, then
 * deletes the whole store via scenarioStore.clearCache(); and the
 * previously-missing onSaved wiring (both in the empty "no scenarios yet"
 * state and the populated one) triggers a refresh after editing a scenario's
 * YAML.
 *
 * No "Regenerate cache" action here — it depended on the same host-registered
 * sweep runner as "Run Sweep" (`useSweepRunStore`/`startSweep`), which isn't
 * available in a plain Boulder install, making the button look broken. "Clear
 * cache" only deletes the store, so it needs no sweep runner.
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
const mockClearCache = vi.fn();
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
    clearCache: mockClearCache,
  }),
}));

let mockScenarioProgress: Record<string, { stage: number | null; stageTotal: number | null }> = {};
vi.mock("@/stores/sweepStore", () => ({
  useSweepRunStore: (selector: (s: unknown) => unknown) =>
    selector({ scenarioProgress: mockScenarioProgress }),
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
    mockClearCache.mockResolvedValue({ cleared: true });
    capturedOnSaved = undefined;
    mockAvailable = true;
    mockScenarios = [{ id: "A", label: "Scenario A", t0_K: 300 }];
    mockAuthoredIds = [];
    mockScenarioProgress = {};
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

  it("Clear cache confirms, then clears the store", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle(/Clear cache/));
    await Promise.resolve();

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockClearCache).toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("does nothing when the Clear cache confirmation is dismissed", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle(/Clear cache/));

    expect(mockClearCache).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
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

  it("shows a mixed list: computed scenarios alongside authored-but-pending ones", () => {
    mockScenarios = [{ id: "A", label: "Scenario A", t0_K: 300 }];
    mockAuthoredIds = ["A", "pending_b"];
    render(<ScenarioPane />);

    expect(screen.getByText("Scenario A")).toBeInTheDocument();
    expect(screen.getByText("pending_b")).toBeInTheDocument();
    expect(screen.getByText("Not computed yet")).toBeInTheDocument();
  });

  it('shows "Calculating…" for the scenario currently mid-sweep, in place of its status', () => {
    mockScenarios = [{ id: "A", label: "Scenario A", t0_K: 300 }];
    mockAuthoredIds = ["A", "cold_feed"];
    mockScenarioProgress = { cold_feed: { stage: 1, stageTotal: 3 } };
    render(<ScenarioPane />);

    expect(screen.getByText("Calculating…")).toBeInTheDocument();
    // The computed, not-currently-solving row keeps its own status.
    expect(screen.queryByText("Not computed yet")).not.toBeInTheDocument();
  });

  it("clicking a pending (not-yet-computed) row still calls setActive", () => {
    mockScenarios = [];
    mockAuthoredIds = ["pending_a"];
    render(<ScenarioPane />);

    fireEvent.click(screen.getByText("pending_a"));

    expect(mockSetActive).toHaveBeenCalledWith("pending_a");
  });
});
