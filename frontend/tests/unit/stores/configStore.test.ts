import { describe, it, expect, beforeEach, vi } from "vitest";
import { useConfigStore } from "@/stores/configStore";
import * as configsApi from "@/api/configs";

describe("useConfigStore", () => {
  beforeEach(() => {
    useConfigStore.setState({
      config: { nodes: [], connections: [] },
      fileName: null,
      originalYaml: "",
      dirty: false,
    });
    vi.restoreAllMocks();
  });

  it("should set config", () => {
    const config = {
      nodes: [
        { id: "r1", type: "IdealGasReactor", properties: { temperature: 1000 } },
      ],
      connections: [],
    };
    useConfigStore.getState().setConfig(config, "test.yaml", "nodes:\n  - id: r1");

    expect(useConfigStore.getState().config).toEqual(config);
    expect(useConfigStore.getState().fileName).toBe("test.yaml");
  });

  it("should add node", () => {
    const store = useConfigStore.getState();
    store.addNode({
      id: "reactor1",
      type: "IdealGasReactor",
      properties: { temperature: 1000, pressure: 101325 },
    });

    expect(useConfigStore.getState().config.nodes).toHaveLength(1);
    expect(useConfigStore.getState().config.nodes[0].id).toBe("reactor1");
  });

  it("should prevent duplicate node IDs", () => {
    const store = useConfigStore.getState();
    store.addNode({ id: "r1", type: "IdealGasReactor", properties: {} });

    expect(() => {
      useConfigStore.getState().addNode({ id: "r1", type: "Reservoir", properties: {} });
    }).toThrow("Node with ID r1 already exists");
  });

  it("should remove node and connected edges", () => {
    const store = useConfigStore.getState();
    store.addNode({ id: "r1", type: "IdealGasReactor", properties: {} });
    store.addNode({ id: "r2", type: "Reservoir", properties: {} });
    store.addConnection({
      id: "mfc1",
      type: "MassFlowController",
      source: "r1",
      target: "r2",
      properties: {},
    });

    expect(useConfigStore.getState().config.connections).toHaveLength(1);

    useConfigStore.getState().removeNode("r1");

    expect(useConfigStore.getState().config.nodes).toHaveLength(1);
    expect(useConfigStore.getState().config.connections).toHaveLength(0);
  });

  it("should update node properties", () => {
    const store = useConfigStore.getState();
    store.addNode({
      id: "r1",
      type: "IdealGasReactor",
      properties: { temperature: 300 },
    });

    useConfigStore.getState().updateNode("r1", {
      properties: { temperature: 1000, pressure: 101325 },
    });

    const node = useConfigStore.getState().config.nodes[0];
    expect(node.properties.temperature).toBe(1000);
    expect(node.properties.pressure).toBe(101325);
  });

  it("should reset config", () => {
    const store = useConfigStore.getState();
    store.addNode({ id: "r1", type: "IdealGasReactor", properties: {} });
    store.resetConfig();

    expect(useConfigStore.getState().config.nodes).toHaveLength(0);
    expect(useConfigStore.getState().fileName).toBeNull();
  });

  it("marks the store dirty after a mutation and clears it on setConfig", () => {
    const store = useConfigStore.getState();
    expect(useConfigStore.getState().dirty).toBe(false);

    store.addNode({ id: "r1", type: "IdealGasReactor", properties: {} });
    expect(useConfigStore.getState().dirty).toBe(true);

    useConfigStore.getState().setConfig({ nodes: [], connections: [] }, "test.yaml", "nodes: []");
    expect(useConfigStore.getState().dirty).toBe(false);
  });

  it("assigns a newly added node to the single existing stage group", () => {
    const store = useConfigStore.getState();
    store.addNode({ id: "r1", type: "IdealGasReactor", properties: {}, group: "stage_a" });

    store.addNode({ id: "r2", type: "Reservoir", properties: {} });

    const r2 = useConfigStore.getState().config.nodes.find((n) => n.id === "r2");
    expect(r2?.group).toBe("stage_a");
  });

  it("leaves group unresolved when multiple stages exist and none is specified", () => {
    const store = useConfigStore.getState();
    store.addNode({ id: "r1", type: "IdealGasReactor", properties: {}, group: "stage_a" });
    store.addNode({ id: "r2", type: "IdealGasReactor", properties: {}, group: "stage_b" });

    store.addNode({ id: "r3", type: "Reservoir", properties: {} });

    const r3 = useConfigStore.getState().config.nodes.find((n) => n.id === "r3");
    expect(r3?.group).toBeUndefined();
  });

  it("respects an explicit group argument over inference", () => {
    const store = useConfigStore.getState();
    store.addNode({ id: "r1", type: "IdealGasReactor", properties: {}, group: "stage_a" });

    store.addNode({ id: "r2", type: "Reservoir", properties: {} }, "stage_b");

    const r2 = useConfigStore.getState().config.nodes.find((n) => n.id === "r2");
    expect(r2?.group).toBe("stage_b");
  });

  it("syncYaml merges the live config into originalYaml and clears dirty", async () => {
    const syncSpy = vi
      .spyOn(configsApi, "syncConfig")
      .mockResolvedValue({ yaml: "nodes:\n  - id: r1\n", warnings: [] });

    useConfigStore.setState({ originalYaml: "nodes: []\n" });
    useConfigStore.getState().addNode({ id: "r1", type: "IdealGasReactor", properties: {} });
    expect(useConfigStore.getState().dirty).toBe(true);

    await useConfigStore.getState().syncYaml();

    expect(syncSpy).toHaveBeenCalledTimes(1);
    expect(useConfigStore.getState().originalYaml).toBe("nodes:\n  - id: r1\n");
    expect(useConfigStore.getState().dirty).toBe(false);
  });

  it("syncYaml is a no-op when the store is not dirty", async () => {
    const syncSpy = vi.spyOn(configsApi, "syncConfig");
    useConfigStore.setState({ originalYaml: "nodes: []\n", dirty: false });

    await useConfigStore.getState().syncYaml();

    expect(syncSpy).not.toHaveBeenCalled();
  });
});
