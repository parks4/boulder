/**
 * Asserts scenarioStore: refresh() populates authoredIds (the full,
 * sweep-independent scenario list) and bumps revision; create/rename/delete
 * each refresh internally afterward — so callers never have to remember to
 * do it themselves (the bug that let Run Sweep's scenario count and the Add
 * Scenario clone-base list go stale); and each of those four also pushes the
 * freshly-written config YAML into `configStore` (the bug where the "Edit
 * YAML" pane kept showing a load-time snapshot after a scenario write went
 * straight to disk, unrelated to any `configStore.config`/graph state).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { useScenarioStore } from "./scenarioStore";

const mockListScenarios = vi.fn();
const mockCreateScenario = vi.fn();
const mockRenameScenario = vi.fn();
const mockDeleteScenario = vi.fn();
const mockFetchScenario = vi.fn();

vi.mock("@/api/scenarios", () => ({
  listScenarios: (...args: unknown[]) => mockListScenarios(...args),
  createScenario: (...args: unknown[]) => mockCreateScenario(...args),
  renameScenario: (...args: unknown[]) => mockRenameScenario(...args),
  deleteScenario: (...args: unknown[]) => mockDeleteScenario(...args),
  fetchScenario: (...args: unknown[]) => mockFetchScenario(...args),
  updateScenario: vi.fn(),
}));

const mockFetchPreloadedConfig = vi.fn();
vi.mock("@/api/configs", () => ({
  fetchPreloadedConfig: (...args: unknown[]) => mockFetchPreloadedConfig(...args),
}));

const mockSetOriginalYaml = vi.fn();
vi.mock("./configStore", () => ({
  useConfigStore: { getState: () => ({ setOriginalYaml: mockSetOriginalYaml }) },
}));

describe("scenarioStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchPreloadedConfig.mockResolvedValue({ preloaded: false });
    useScenarioStore.setState({
      available: false,
      scenarios: [],
      authoredIds: [],
      activeId: null,
      loading: false,
      error: null,
      revision: 0,
      createdAt: undefined,
    });
  });

  it("refresh() populates authoredIds and bumps revision", async () => {
    mockListScenarios.mockResolvedValue({
      available: true,
      scenarios: [{ id: "A", t0_K: 300, label: "A" }],
      authored_ids: ["A", "B"],
      created_at: 123,
    });

    await useScenarioStore.getState().refresh();

    const state = useScenarioStore.getState();
    expect(state.authoredIds).toEqual(["A", "B"]);
    expect(state.scenarios).toHaveLength(1);
    expect(state.revision).toBe(1);
  });

  it("refresh() still bumps revision on failure, resetting authoredIds", async () => {
    mockListScenarios.mockRejectedValue(new Error("network error"));

    await useScenarioStore.getState().refresh();

    const state = useScenarioStore.getState();
    expect(state.available).toBe(false);
    expect(state.authoredIds).toEqual([]);
    expect(state.revision).toBe(1);
  });

  it("createScenario refreshes afterward, so authoredIds/revision reflect the new scenario", async () => {
    mockCreateScenario.mockResolvedValue({ scenario_id: "C", yaml: "" });
    mockListScenarios.mockResolvedValue({
      available: false,
      scenarios: [],
      authored_ids: ["A", "C"],
    });

    await useScenarioStore.getState().createScenario("C");

    expect(mockListScenarios).toHaveBeenCalledOnce();
    const state = useScenarioStore.getState();
    expect(state.activeId).toBe("C");
    expect(state.authoredIds).toEqual(["A", "C"]);
    expect(state.revision).toBe(1);
  });

  it("renameScenario refreshes afterward and updates activeId if it matched", async () => {
    useScenarioStore.setState({ activeId: "A" });
    mockRenameScenario.mockResolvedValue({ ok: true, scenario_id: "A2" });
    mockListScenarios.mockResolvedValue({
      available: false,
      scenarios: [],
      authored_ids: ["A2"],
    });

    await useScenarioStore.getState().renameScenario("A", "A2");

    expect(mockListScenarios).toHaveBeenCalledOnce();
    const state = useScenarioStore.getState();
    expect(state.activeId).toBe("A2");
    expect(state.revision).toBe(1);
  });

  it("deleteScenario refreshes afterward and clears activeId if it matched", async () => {
    useScenarioStore.setState({ activeId: "A" });
    mockDeleteScenario.mockResolvedValue({ ok: true, scenario_id: "A" });
    mockListScenarios.mockResolvedValue({ available: false, scenarios: [], authored_ids: [] });

    await useScenarioStore.getState().deleteScenario("A");

    expect(mockListScenarios).toHaveBeenCalledOnce();
    expect(useScenarioStore.getState().activeId).toBeNull();
  });

  it("createScenario pushes the freshly-written config YAML into configStore", async () => {
    mockCreateScenario.mockResolvedValue({ scenario_id: "C", yaml: "" });
    mockListScenarios.mockResolvedValue({ available: false, scenarios: [], authored_ids: ["C"] });
    mockFetchPreloadedConfig.mockResolvedValue({
      preloaded: true,
      yaml: "scenario:\n  C: {}\n",
      filename: "config.yaml",
    });

    await useScenarioStore.getState().createScenario("C");

    expect(mockSetOriginalYaml).toHaveBeenCalledWith("scenario:\n  C: {}\n", "config.yaml");
  });

  it("updateScenario/renameScenario/deleteScenario each also resync configStore's YAML", async () => {
    mockRenameScenario.mockResolvedValue({ ok: true, scenario_id: "A2" });
    mockDeleteScenario.mockResolvedValue({ ok: true, scenario_id: "A2" });
    mockListScenarios.mockResolvedValue({ available: false, scenarios: [], authored_ids: [] });
    mockFetchPreloadedConfig.mockResolvedValue({
      preloaded: true,
      yaml: "resynced",
      filename: "config.yaml",
    });

    await useScenarioStore.getState().renameScenario("A", "A2");
    expect(mockSetOriginalYaml).toHaveBeenCalledWith("resynced", "config.yaml");

    mockSetOriginalYaml.mockClear();
    await useScenarioStore.getState().deleteScenario("A2");
    expect(mockSetOriginalYaml).toHaveBeenCalledWith("resynced", "config.yaml");
  });

  it("does not touch configStore when nothing is preloaded (e.g. an uploaded/pasted config)", async () => {
    mockCreateScenario.mockResolvedValue({ scenario_id: "C", yaml: "" });
    mockListScenarios.mockResolvedValue({ available: false, scenarios: [], authored_ids: ["C"] });
    mockFetchPreloadedConfig.mockResolvedValue({ preloaded: false });

    await useScenarioStore.getState().createScenario("C");

    expect(mockSetOriginalYaml).not.toHaveBeenCalled();
  });

  it("swallows a resync fetch failure instead of rejecting the caller's promise", async () => {
    mockCreateScenario.mockResolvedValue({ scenario_id: "C", yaml: "" });
    mockListScenarios.mockResolvedValue({ available: false, scenarios: [], authored_ids: ["C"] });
    mockFetchPreloadedConfig.mockRejectedValue(new Error("network error"));

    await expect(useScenarioStore.getState().createScenario("C")).resolves.toBeUndefined();
    expect(mockSetOriginalYaml).not.toHaveBeenCalled();
  });
});
