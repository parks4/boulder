/**
 * Asserts ScenarioPane: deleting a scenario confirms first, then reports
 * whether a cached result was purged too; "Clear cache" confirms, then
 * deletes the whole store via scenarioStore.clearCache(); and BASELINE (the
 * base config's own unmodified run-set entry, not a real authored overlay)
 * is treated specially -- no delete button, and its "edit" opens the full
 * YAML pane instead of the scoped (and otherwise 404ing) overlay editor.
 * The scoped editor modal itself now lives once in AppShell (see its own
 * test), not owned by this pane -- only the open-editor wiring is asserted
 * here.
 *
 * No "Regenerate cache" action here — it depended on the same host-registered
 * sweep runner as "Run Sweep" (`useSweepRunStore`/`startSweep`), which isn't
 * available in a plain Boulder install, making the button look broken. "Clear
 * cache" only deletes the store, so it needs no sweep runner.
 *
 * A scenario's only name is its `scenarios:` mapping key, shown as the row
 * title; `metadata.description` is a subtitle (editable via "Edit scenario
 * YAML"), never an alternative name. No "Rename scenario" control here.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ScenarioPane } from "./ScenarioPane";

const mockRefresh = vi.fn();
const mockSetActive = vi.fn();
const mockDeleteScenario = vi.fn();
const mockClearCache = vi.fn();
const mockClearEntryCache = vi.fn();
let mockAvailable = true;
let mockScenarios: Array<{ id: string; label: string; t0_K: number }> = [
  { id: "A", label: "Scenario A", t0_K: 300 },
];
let mockAuthoredIds: string[] = [];
// `metadata.description` per overlay -- the live, pre-solve source of the
// pane's subtitle (see `overlayDescription`); the title is always the id.
let mockOverlays: Record<string, { metadata?: Record<string, unknown> }> = {
  A: { metadata: { description: "Scenario A" } },
};

vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: () => ({
    available: mockAvailable,
    scenarios: mockScenarios,
    authoredIds: mockAuthoredIds,
    overlays: mockOverlays,
    createdAt: undefined,
    activeId: null,
    loading: false,
    error: null,
    refresh: mockRefresh,
    setActive: mockSetActive,
    deleteScenario: mockDeleteScenario,
    clearCache: mockClearCache,
    clearEntryCache: mockClearEntryCache,
  }),
}));

let mockScenarioProgress: Record<string, { stage: number | null; stageTotal: number | null }> = {};
let mockPinnedId: string | null = null;
vi.mock("@/stores/sweepStore", async (importOriginal) => ({
  // Real follow rule (`followedScenarioId`), mocked store state.
  ...(await importOriginal<typeof import("@/stores/sweepStore")>()),
  useSweepRunStore: (selector: (s: unknown) => unknown) =>
    selector({ scenarioProgress: mockScenarioProgress, pinnedId: mockPinnedId }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/modals/AddScenarioModal", () => ({
  AddScenarioModal: () => null,
}));

const mockOpenYamlPane = vi.fn();
const mockOpenScenarioYamlEditor = vi.fn();
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: unknown) => unknown) =>
    selector({
      openYamlPane: mockOpenYamlPane,
      openScenarioYamlEditor: mockOpenScenarioYamlEditor,
    }),
}));

vi.mock("./SweepResultsPlot", () => ({
  SweepResultsPlot: () => null,
}));

describe("ScenarioPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClearCache.mockResolvedValue({ cleared: true });
    mockClearEntryCache.mockResolvedValue({ cleared: true });
    mockAvailable = true;
    mockScenarios = [{ id: "A", label: "Scenario A", t0_K: 300 }];
    mockAuthoredIds = [];
    mockOverlays = { A: { metadata: { description: "Scenario A" } } };
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

  it("a row's eraser confirms, then clears that scenario's cache only", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ScenarioPane />);

    fireEvent.click(screen.getByTitle(/Clear this scenario's cached result/));
    await Promise.resolve();

    expect(mockClearEntryCache).toHaveBeenCalledWith("A");
    expect(mockClearCache).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("an uncomputed row has no eraser — there is no cached result to clear", () => {
    mockScenarios = [];
    mockAuthoredIds = ["pending_a"];
    render(<ScenarioPane />);

    expect(screen.queryByTitle(/Clear this scenario's cached result/)).toBeNull();
  });

  it("opens the scoped overlay editor for a regular scenario's pencil", () => {
    render(<ScenarioPane />);
    fireEvent.click(screen.getByTitle("Edit scenario YAML"));
    expect(mockOpenScenarioYamlEditor).toHaveBeenCalledWith("A");
    expect(mockOpenYamlPane).not.toHaveBeenCalled();
  });

  it("BASELINE gets a disabled (barred) delete slot instead of a working delete button", () => {
    mockAuthoredIds = ["BASELINE", "A"];
    render(<ScenarioPane />);
    // Only the non-baseline row ("A") gets a real delete button...
    expect(screen.getAllByTitle("Delete scenario")).toHaveLength(1);
    // ...but BASELINE still occupies the same icon slot, so rows stay aligned.
    const barred = screen.getByTitle(/cannot be deleted/);
    expect(barred.tagName).not.toBe("BUTTON");
  });

  it("BASELINE's pencil opens the full YAML pane, not the scoped editor", () => {
    mockAuthoredIds = ["BASELINE", "A"];
    render(<ScenarioPane />);
    fireEvent.click(screen.getByTitle(/Edit YAML \(the base config/));
    expect(mockOpenYamlPane).toHaveBeenCalledOnce();
    expect(mockOpenScenarioYamlEditor).not.toHaveBeenCalled();
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

    // The id is the row title; the overlay's description is its subtitle.
    expect(screen.getByText("A")).toBeInTheDocument();
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

  it("highlights the scenario being followed mid-sweep, not the stale selection", () => {
    // The graph and the results card follow the solver during a sweep; the
    // row highlight must move with them instead of staying on whatever was
    // selected before the sweep started (auto-follow never calls setActive).
    mockScenarios = [{ id: "A", label: "Scenario A", t0_K: 300 }];
    mockAuthoredIds = ["A", "cold_feed"];
    mockScenarioProgress = { cold_feed: { stage: 1, stageTotal: 3 } };
    render(<ScenarioPane />);

    expect(document.getElementById("scenario-cold_feed")).toHaveClass("border-blue-500");
    expect(document.getElementById("scenario-A")).not.toHaveClass("border-blue-500");
  });

  it("keeps the highlight on a scenario the user pinned mid-sweep", () => {
    mockScenarios = [{ id: "A", label: "Scenario A", t0_K: 300 }];
    mockAuthoredIds = ["A", "cold_feed"];
    mockScenarioProgress = { cold_feed: { stage: 1, stageTotal: 3 } };
    mockPinnedId = "A";
    render(<ScenarioPane />);

    // Pinned but not solving: nothing is followed, so the highlight falls
    // back to the store's own selection (null in this mock) -- never the solver.
    expect(document.getElementById("scenario-cold_feed")).not.toHaveClass("border-blue-500");
    mockPinnedId = null;
  });

  it("clicking a pending (not-yet-computed) row still calls setActive", () => {
    mockScenarios = [];
    mockAuthoredIds = ["pending_a"];
    render(<ScenarioPane />);

    fireEvent.click(screen.getByText("pending_a"));

    expect(mockSetActive).toHaveBeenCalledWith("pending_a");
  });
});
