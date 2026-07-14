import { create } from "zustand";
import type { ConfigConnection, ConfigNode, NormalizedConfig } from "@/types/config";
import { syncConfig } from "@/api/configs";

interface ConfigState {
  config: NormalizedConfig;
  fileName: string | null;
  originalYaml: string;
  /** True when the live config has diverged from `originalYaml` since the last sync/load. */
  dirty: boolean;

  // Actions
  setConfig: (config: NormalizedConfig, fileName?: string | null, yaml?: string) => void;
  resetConfig: () => void;
  addNode: (node: ConfigNode, group?: string | null) => void;
  updateNode: (id: string, updates: Partial<ConfigNode>) => void;
  removeNode: (id: string) => void;
  addConnection: (conn: ConfigConnection, group?: string | null) => void;
  updateConnection: (id: string, updates: Partial<ConfigConnection>) => void;
  removeConnection: (id: string) => void;
  /** Merge the live config into `originalYaml` (via /configs/sync) and refresh it. No-op if not dirty. */
  syncYaml: () => Promise<void>;
}

const EMPTY_CONFIG: NormalizedConfig = {
  nodes: [],
  connections: [],
};

/** When every existing node/connection shares the same single stage group, new elements should join it too. */
function inferSingleGroup(config: NormalizedConfig): string | null | undefined {
  const groups = new Set(
    [...config.nodes.map((n) => n.group), ...config.connections.map((c) => c.group)].filter(
      (g): g is string => typeof g === "string" && g.length > 0,
    ),
  );
  return groups.size === 1 ? [...groups][0] : undefined;
}

export const useConfigStore = create<ConfigState>((set, get) => ({
  config: EMPTY_CONFIG,
  fileName: null,
  originalYaml: "",
  dirty: false,

  setConfig: (config, fileName, yaml) =>
    set({
      config,
      fileName: fileName ?? get().fileName,
      originalYaml: yaml ?? get().originalYaml,
      dirty: false,
    }),

  resetConfig: () =>
    set({ config: EMPTY_CONFIG, fileName: null, originalYaml: "", dirty: false }),

  addNode: (node, group) => {
    const { config } = get();
    if (config.nodes.some((n) => n.id === node.id)) {
      throw new Error(`Node with ID ${node.id} already exists`);
    }
    const resolvedGroup = group ?? node.group ?? inferSingleGroup(config);
    set({
      config: { ...config, nodes: [...config.nodes, { ...node, group: resolvedGroup }] },
      dirty: true,
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
      dirty: true,
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
      dirty: true,
    });
  },

  addConnection: (conn, group) => {
    const { config } = get();
    if (config.connections.some((c) => c.id === conn.id)) {
      throw new Error(`Connection with ID ${conn.id} already exists`);
    }
    const resolvedGroup = group ?? conn.group ?? inferSingleGroup(config);
    set({
      config: {
        ...config,
        connections: [...config.connections, { ...conn, group: resolvedGroup }],
      },
      dirty: true,
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
      dirty: true,
    });
  },

  removeConnection: (id) => {
    const { config } = get();
    set({
      config: {
        ...config,
        connections: config.connections.filter((c) => c.id !== id),
      },
      dirty: true,
    });
  },

  syncYaml: async () => {
    const { config, originalYaml, dirty } = get();
    if (!dirty || !originalYaml) return;
    const resp = await syncConfig(config, originalYaml);
    set({ originalYaml: resp.yaml, dirty: false });
  },
}));
