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
const mockClearScenarioCache = vi.fn();
const mockFetchScenarioPreview = vi.fn();

vi.mock("@/api/scenarios", () => ({
  listScenarios: (...args: unknown[]) => mockListScenarios(...args),
  createScenario: (...args: unknown[]) => mockCreateScenario(...args),
  renameScenario: (...args: unknown[]) => mockRenameScenario(...args),
  deleteScenario: (...args: unknown[]) => mockDeleteScenario(...args),
  fetchScenario: (...args: unknown[]) => mockFetchScenario(...args),
  clearScenarioCache: (...args: unknown[]) => mockClearScenarioCache(...args),
  fetchScenarioPreview: (...args: unknown[]) => mockFetchScenarioPreview(...args),
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
    mockFetchScenarioPreview.mockResolvedValue({
      scenario_id: "unset",
      nodes: [],
      connections: [],
    });
    useScenarioStore.setState({
      available: false,
      scenarios: [],
      authoredIds: [],
      activeId: null,
      loading: false,
      error: null,
      revision: 0,
      createdAt: undefined,
      previewId: null,
      previewNodes: null,
      previewConnections: null,
      previewLoading: false,
      previewError: null,
      previewSeq: 0,
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

  it("clearCache refreshes afterward and clears activeId", async () => {
    useScenarioStore.setState({ activeId: "A" });
    mockClearScenarioCache.mockResolvedValue({ ok: true, cleared: true });
    mockListScenarios.mockResolvedValue({ available: false, scenarios: [], authored_ids: ["A"] });

    const result = await useScenarioStore.getState().clearCache();

    expect(mockListScenarios).toHaveBeenCalledOnce();
    expect(result).toEqual({ cleared: true });
    expect(useScenarioStore.getState().activeId).toBeNull();
  });

  it("setActive on an id not yet computed just selects it, without fetching", async () => {
    useScenarioStore.setState({ scenarios: [{ id: "A", t0_K: 300, label: "A" }] });

    await useScenarioStore.getState().setActive("pending_id");

    expect(useScenarioStore.getState().activeId).toBe("pending_id");
    expect(useScenarioStore.getState().error).toBeNull();
    expect(mockFetchScenario).not.toHaveBeenCalled();
  });

  it("deleteScenario clears the preview when the deleted scenario was being previewed", async () => {
    useScenarioStore.setState({
      previewId: "A",
      previewNodes: [{ id: "r1", type: "x", properties: {} }],
      previewConnections: [],
    });
    mockDeleteScenario.mockResolvedValue({ ok: true, scenario_id: "A" });
    mockListScenarios.mockResolvedValue({ available: false, scenarios: [], authored_ids: [] });

    await useScenarioStore.getState().deleteScenario("A");

    const state = useScenarioStore.getState();
    expect(state.previewId).toBeNull();
    expect(state.previewNodes).toBeNull();
  });

  it("setActive on an authored-but-uncomputed scenario loads its preview without fetching a trajectory", async () => {
    mockFetchScenarioPreview.mockResolvedValue({
      scenario_id: "C600_P300",
      nodes: [{ id: "reactor1", type: "IdealGasReactor", properties: { length: 0.6 } }],
      connections: [],
    });

    await useScenarioStore.getState().setActive("C600_P300");

    expect(mockFetchScenario).not.toHaveBeenCalled();
    const state = useScenarioStore.getState();
    expect(state.activeId).toBe("C600_P300");
    expect(state.previewId).toBe("C600_P300");
    expect(state.previewNodes).toEqual([
      { id: "reactor1", type: "IdealGasReactor", properties: { length: 0.6 } },
    ]);
  });

  it("setActive on a computed scenario loads its preview alongside the trajectory", async () => {
    useScenarioStore.setState({ scenarios: [{ id: "A", t0_K: 300, label: "A" }] });
    mockFetchScenario.mockResolvedValue({ reactors_series: {} });
    mockFetchScenarioPreview.mockResolvedValue({
      scenario_id: "A",
      nodes: [{ id: "r1", type: "IdealGasReactor", properties: { length: 1.2 } }],
      connections: [],
    });

    await useScenarioStore.getState().setActive("A");

    expect(mockFetchScenario).toHaveBeenCalledWith("A");
    expect(useScenarioStore.getState().previewNodes).toEqual([
      { id: "r1", type: "IdealGasReactor", properties: { length: 1.2 } },
    ]);
  });

  it("loadPreview surfaces a fetch failure in previewError without throwing", async () => {
    mockFetchScenarioPreview.mockRejectedValue(new Error("boom"));

    await useScenarioStore.getState().setActive("nope");

    expect(useScenarioStore.getState().previewError).toBe("boom");
  });

  it("loadPreview ignores a stale response superseded by a newer selection", async () => {
    let resolveFirst: (v: unknown) => void = () => {};
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });
    mockFetchScenarioPreview.mockImplementationOnce(() => firstPromise);
    mockFetchScenarioPreview.mockImplementationOnce(() =>
      Promise.resolve({
        scenario_id: "B",
        nodes: [{ id: "r1", type: "x", properties: { length: 2 } }],
        connections: [],
      }),
    );

    const p1 = useScenarioStore.getState().setActive("A");
    const p2 = useScenarioStore.getState().setActive("B");
    resolveFirst({
      scenario_id: "A",
      nodes: [{ id: "r1", type: "x", properties: { length: 1 } }],
      connections: [],
    });
    await Promise.all([p1, p2]);

    expect(useScenarioStore.getState().previewId).toBe("B");
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
