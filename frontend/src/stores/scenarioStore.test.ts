/**
 * Asserts scenarioStore: refresh() seeds `overlays`/authoredIds from the
 * server's startup snapshot only on the *first* call — a later refresh()
 * must never clobber local edits with that now-stale snapshot (the whole
 * point of scenario authoring moving in-memory, see scenario_editor.py's
 * module docstring). Every mutator (create/update/rename/delete) applies its
 * response's `overlays` locally instead of refetching/resyncing anything —
 * nothing here touches disk or `configStore` anymore.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { useScenarioStore } from "./scenarioStore";
import { useSimulationStore } from "./simulationStore";

const mockListScenarios = vi.fn();
const mockCreateScenario = vi.fn();
const mockUpdateScenario = vi.fn();
const mockRenameScenario = vi.fn();
const mockDeleteScenario = vi.fn();
const mockFetchScenario = vi.fn();
const mockClearScenarioCache = vi.fn();
const mockFetchScenarioPreview = vi.fn();

vi.mock("@/api/scenarios", () => ({
  BASELINE_SCENARIO_ID: "BASELINE",
  listScenarios: (...args: unknown[]) => mockListScenarios(...args),
  createScenario: (...args: unknown[]) => mockCreateScenario(...args),
  updateScenario: (...args: unknown[]) => mockUpdateScenario(...args),
  renameScenario: (...args: unknown[]) => mockRenameScenario(...args),
  deleteScenario: (...args: unknown[]) => mockDeleteScenario(...args),
  fetchScenario: (...args: unknown[]) => mockFetchScenario(...args),
  clearScenarioCache: (...args: unknown[]) => mockClearScenarioCache(...args),
  fetchScenarioPreview: (...args: unknown[]) => mockFetchScenarioPreview(...args),
}));

describe("scenarioStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchScenarioPreview.mockResolvedValue({
      scenario_id: "unset",
      nodes: [],
      connections: [],
    });
    useScenarioStore.setState({
      available: false,
      scenarios: [],
      authoredIds: [],
      overlays: {},
      overlaysSeeded: false,
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

  it("refresh() seeds overlays/authoredIds from authored_overlays and bumps revision", async () => {
    mockListScenarios.mockResolvedValue({
      available: true,
      scenarios: [{ id: "A", t0_K: 300, label: "A" }],
      authored_ids: ["BASELINE", "A", "B"],
      authored_overlays: { A: { metadata: {} }, B: {} },
      created_at: 123,
    });

    await useScenarioStore.getState().refresh();

    const state = useScenarioStore.getState();
    expect(state.overlays).toEqual({ A: { metadata: {} }, B: {} });
    expect(state.authoredIds).toEqual(["BASELINE", "A", "B"]);
    expect(state.scenarios).toHaveLength(1);
    expect(state.revision).toBe(1);
  });

  it("refresh() still bumps revision on failure, resetting available/scenarios", async () => {
    mockListScenarios.mockRejectedValue(new Error("network error"));

    await useScenarioStore.getState().refresh();

    const state = useScenarioStore.getState();
    expect(state.available).toBe(false);
    expect(state.scenarios).toEqual([]);
    expect(state.revision).toBe(1);
  });

  it("a second refresh() never clobbers locally-edited overlays with the stale server snapshot", async () => {
    mockListScenarios.mockResolvedValue({
      available: false,
      scenarios: [],
      authored_ids: ["BASELINE", "A"],
      authored_overlays: { A: {} },
    });
    await useScenarioStore.getState().refresh();
    expect(useScenarioStore.getState().overlays).toEqual({ A: {} });

    // Something (e.g. createScenario) mutates overlays locally in between.
    useScenarioStore.getState().applyOverlays({ A: {}, B: { metadata: {} } });

    // The server still only knows about "A" (nothing persists there), but a
    // second refresh (e.g. after a sweep finishes) must not overwrite "B".
    mockListScenarios.mockResolvedValue({
      available: true,
      scenarios: [{ id: "A", t0_K: 300, label: "A" }],
      authored_ids: ["BASELINE", "A"],
      authored_overlays: { A: {} },
    });
    await useScenarioStore.getState().refresh();

    const state = useScenarioStore.getState();
    expect(state.overlays).toEqual({ A: {}, B: { metadata: {} } });
    expect(state.available).toBe(true); // unrelated fields still refresh normally
  });

  it("createScenario sends the current overlays and applies the response locally", async () => {
    useScenarioStore.getState().applyOverlays({ A: {} });
    mockCreateScenario.mockResolvedValue({
      scenario_id: "C",
      yaml: "",
      overlays: { A: {}, C: {} },
    });

    const revisionBefore = useScenarioStore.getState().revision;
    await useScenarioStore.getState().createScenario("C");

    expect(mockCreateScenario).toHaveBeenCalledWith({ A: {} }, "C", undefined, undefined);
    expect(mockListScenarios).not.toHaveBeenCalled(); // no refresh -- nothing to resync from disk
    const state = useScenarioStore.getState();
    expect(state.activeId).toBe("C");
    expect(state.overlays).toEqual({ A: {}, C: {} });
    expect(state.authoredIds).toEqual(["BASELINE", "A", "C"]);
    expect(state.revision).toBe(revisionBefore + 1);
  });

  it("updateScenario applies the response's overlays locally", async () => {
    useScenarioStore.getState().applyOverlays({ A: {} });
    mockUpdateScenario.mockResolvedValue({
      scenario_id: "A",
      yaml: "torch_eff: 0.5\n",
      overlays: { A: { torch_eff: 0.5 } },
    });

    await useScenarioStore.getState().updateScenario("A", "torch_eff: 0.5\n");

    expect(mockUpdateScenario).toHaveBeenCalledWith({ A: {} }, "A", "torch_eff: 0.5\n");
    expect(useScenarioStore.getState().overlays).toEqual({ A: { torch_eff: 0.5 } });
  });

  it("renameScenario applies the response's overlays and updates activeId if it matched", async () => {
    useScenarioStore.setState({ activeId: "A" });
    useScenarioStore.getState().applyOverlays({ A: {} });
    mockRenameScenario.mockResolvedValue({ ok: true, scenario_id: "A2", overlays: { A2: {} } });

    await useScenarioStore.getState().renameScenario("A", "A2");

    expect(mockRenameScenario).toHaveBeenCalledWith({ A: {} }, "A", "A2");
    const state = useScenarioStore.getState();
    expect(state.activeId).toBe("A2");
    expect(state.overlays).toEqual({ A2: {} });
  });

  it("deleteScenario applies the response's overlays and clears activeId if it matched", async () => {
    useScenarioStore.setState({ activeId: "A" });
    useScenarioStore.getState().applyOverlays({ A: {} });
    mockDeleteScenario.mockResolvedValue({
      ok: true,
      scenario_id: "A",
      cache_purged: false,
      overlays: {},
    });

    await useScenarioStore.getState().deleteScenario("A");

    expect(mockDeleteScenario).toHaveBeenCalledWith({ A: {} }, "A");
    expect(useScenarioStore.getState().activeId).toBeNull();
    expect(useScenarioStore.getState().overlays).toEqual({});
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

  it("setActive on an id not yet computed clears a previous scenario's stale results, so ReactorGraph stops showing them as computed", async () => {
    useScenarioStore.setState({ scenarios: [{ id: "A", t0_K: 300, label: "A" }] });
    useSimulationStore.getState().setResults({ reactors_series: {}, code_str: "" } as never);

    await useScenarioStore.getState().setActive("pending_id");

    expect(useSimulationStore.getState().results).toBeNull();
  });

  it("deleteScenario clears the preview when the deleted scenario was being previewed", async () => {
    useScenarioStore.setState({
      previewId: "A",
      previewNodes: [{ id: "r1", type: "x", properties: {} }],
      previewConnections: [],
    });
    mockDeleteScenario.mockResolvedValue({ ok: true, scenario_id: "A", overlays: {} });

    await useScenarioStore.getState().deleteScenario("A");

    const state = useScenarioStore.getState();
    expect(state.previewId).toBeNull();
    expect(state.previewNodes).toBeNull();
  });

  it("setActive on an authored-but-uncomputed scenario loads its preview (using its current overlay) without fetching a trajectory", async () => {
    useScenarioStore.getState().applyOverlays({ C600_P300: { length: 0.6 } });
    mockFetchScenarioPreview.mockResolvedValue({
      scenario_id: "C600_P300",
      nodes: [{ id: "reactor1", type: "IdealGasReactor", properties: { length: 0.6 } }],
      connections: [],
    });

    await useScenarioStore.getState().setActive("C600_P300");

    expect(mockFetchScenarioPreview).toHaveBeenCalledWith("C600_P300", { length: 0.6 });
    expect(mockFetchScenario).not.toHaveBeenCalled();
    const state = useScenarioStore.getState();
    expect(state.activeId).toBe("C600_P300");
    expect(state.previewId).toBe("C600_P300");
    expect(state.previewNodes).toEqual([
      { id: "reactor1", type: "IdealGasReactor", properties: { length: 0.6 } },
    ]);
  });

  it("setActive on BASELINE previews with an empty overlay", async () => {
    useScenarioStore.getState().applyOverlays({ A: { length: 0.6 } });

    await useScenarioStore.getState().setActive("BASELINE");

    expect(mockFetchScenarioPreview).toHaveBeenCalledWith("BASELINE", {});
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

  it("clears the previous preview before awaiting the new one", async () => {
    // Selecting a scenario used to leave the *previous* scenario's preview in
    // place until the fetch resolved, so the Properties panel rendered another
    // scenario's numbers under the new selection, styled as an override with
    // nothing marking them stale. Measured at ~80 ms against a real model, but
    // it scales with server load, and a wrong number presented as fact is the
    // bug regardless of how briefly it shows.
    mockFetchScenarioPreview.mockResolvedValueOnce({
      scenario_id: "A",
      nodes: [{ id: "outlet", type: "OutletSink", properties: { pressure: 200000 } }],
      connections: [],
    });
    await useScenarioStore.getState().setActive("A");
    expect(useScenarioStore.getState().previewNodes).toEqual([
      { id: "outlet", type: "OutletSink", properties: { pressure: 200000 } },
    ]);

    // Now select another scenario whose preview has not resolved yet.
    let resolveSecond: (v: unknown) => void = () => {};
    mockFetchScenarioPreview.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSecond = resolve;
        }),
    );
    const pending = useScenarioStore.getState().setActive("B");

    const midFlight = useScenarioStore.getState();
    expect(midFlight.previewLoading).toBe(true);
    expect(midFlight.previewNodes).toBeNull();
    expect(midFlight.previewConnections).toBeNull();
    expect(midFlight.previewId).toBeNull();

    resolveSecond({
      scenario_id: "B",
      nodes: [{ id: "outlet", type: "OutletSink", properties: { pressure: 300000 } }],
      connections: [],
    });
    await pending;

    expect(useScenarioStore.getState().previewId).toBe("B");
    expect(useScenarioStore.getState().previewNodes).toEqual([
      { id: "outlet", type: "OutletSink", properties: { pressure: 300000 } },
    ]);
  });
});
