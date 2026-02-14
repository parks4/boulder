import { describe, it, expect, beforeEach } from "vitest";
import { useConfigStore } from "@/stores/configStore";

describe("useConfigStore", () => {
  beforeEach(() => {
    useConfigStore.setState({
      config: { nodes: [], connections: [] },
      fileName: null,
      originalYaml: "",
    });
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
});
