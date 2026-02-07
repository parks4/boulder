import { create } from "zustand";
import type { ConfigConnection, ConfigNode, NormalizedConfig } from "@/types/config";

interface ConfigState {
  config: NormalizedConfig;
  fileName: string | null;
  originalYaml: string;

  // Actions
  setConfig: (config: NormalizedConfig, fileName?: string | null, yaml?: string) => void;
  resetConfig: () => void;
  addNode: (node: ConfigNode) => void;
  updateNode: (id: string, updates: Partial<ConfigNode>) => void;
  removeNode: (id: string) => void;
  addConnection: (conn: ConfigConnection) => void;
  updateConnection: (id: string, updates: Partial<ConfigConnection>) => void;
  removeConnection: (id: string) => void;
}

const EMPTY_CONFIG: NormalizedConfig = {
  nodes: [],
  connections: [],
};

export const useConfigStore = create<ConfigState>((set, get) => ({
  config: EMPTY_CONFIG,
  fileName: null,
  originalYaml: "",

  setConfig: (config, fileName, yaml) =>
    set({
      config,
      fileName: fileName ?? get().fileName,
      originalYaml: yaml ?? get().originalYaml,
    }),

  resetConfig: () =>
    set({ config: EMPTY_CONFIG, fileName: null, originalYaml: "" }),

  addNode: (node) => {
    const { config } = get();
    if (config.nodes.some((n) => n.id === node.id)) {
      throw new Error(`Node with ID ${node.id} already exists`);
    }
    set({
      config: { ...config, nodes: [...config.nodes, node] },
    });
  },

  updateNode: (id, updates) => {
    const { config } = get();
    set({
      config: {
        ...config,
        nodes: config.nodes.map((n) =>
          n.id === id ? { ...n, ...updates } : n,
        ),
      },
    });
  },

  removeNode: (id) => {
    const { config } = get();
    set({
      config: {
        ...config,
        nodes: config.nodes.filter((n) => n.id !== id),
        connections: config.connections.filter(
          (c) => c.source !== id && c.target !== id,
        ),
      },
    });
  },

  addConnection: (conn) => {
    const { config } = get();
    if (config.connections.some((c) => c.id === conn.id)) {
      throw new Error(`Connection with ID ${conn.id} already exists`);
    }
    set({
      config: { ...config, connections: [...config.connections, conn] },
    });
  },

  updateConnection: (id, updates) => {
    const { config } = get();
    set({
      config: {
        ...config,
        connections: config.connections.map((c) =>
          c.id === id ? { ...c, ...updates } : c,
        ),
      },
    });
  },

  removeConnection: (id) => {
    const { config } = get();
    set({
      config: {
        ...config,
        connections: config.connections.filter((c) => c.id !== id),
      },
    });
  },
}));
