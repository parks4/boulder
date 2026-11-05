/**
 * Asserts configStore's `setOriginalYaml`: it replaces only the on-disk YAML
 * snapshot, leaving the live graph (`config`) and `dirty` flag untouched —
 * so an out-of-band disk write (e.g. scenario authoring) can refresh what
 * the YAML pane displays without discarding any unsaved node/connection
 * edits sitting in `config`.
 *
 * Also asserts `syncYaml` on a `from:` leaf with a canvas edit: the server's
 * merged YAML is adopted and the session is clean; a sync the server rejects
 * rejects (so Run/Sweep stop) and leaves the session dirty.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

const mockSyncConfig = vi.fn();
vi.mock("@/api/configs", () => ({
  syncConfig: (...args: unknown[]) => mockSyncConfig(...args),
}));

import { useConfigStore } from "./configStore";

describe("configStore", () => {
  beforeEach(() => {
    useConfigStore.setState({
      config: { nodes: [{ id: "a", type: "Reservoir" }], connections: [] } as never,
      fileName: "original.yaml",
      originalYaml: "old: yaml",
      dirty: true,
    });
  });

  it("setOriginalYaml replaces the yaml snapshot without touching config or dirty", () => {
    useConfigStore.getState().setOriginalYaml("new: yaml");

    const state = useConfigStore.getState();
    expect(state.originalYaml).toBe("new: yaml");
    expect(state.config.nodes).toHaveLength(1);
    expect(state.dirty).toBe(true);
    expect(state.fileName).toBe("original.yaml");
  });

  it("setOriginalYaml updates fileName when given one", () => {
    useConfigStore.getState().setOriginalYaml("new: yaml", "renamed.yaml");

    expect(useConfigStore.getState().fileName).toBe("renamed.yaml");
  });

  it("setConfig (unlike setOriginalYaml) does reset dirty and replace config", () => {
    useConfigStore.getState().setConfig({ nodes: [], connections: [] }, undefined, "new: yaml");

    const state = useConfigStore.getState();
    expect(state.dirty).toBe(false);
    expect(state.config.nodes).toHaveLength(0);
  });

  it("syncYaml on a from: leaf adopts the server's merged YAML and clears dirty", async () => {
    useConfigStore.setState({ originalYaml: "from: base.yaml\nmetadata: {}\n" });
    mockSyncConfig.mockResolvedValueOnce({ yaml: "merged: yaml" });

    await useConfigStore.getState().syncYaml();

    expect(mockSyncConfig).toHaveBeenCalledWith(
      expect.objectContaining({ nodes: expect.any(Array) }),
      "from: base.yaml\nmetadata: {}\n",
    );
    const state = useConfigStore.getState();
    expect(state.originalYaml).toBe("merged: yaml");
    expect(state.dirty).toBe(false);
  });

  it("syncYaml rejects when the edit cannot be merged back, and stays dirty", async () => {
    useConfigStore.setState({ originalYaml: "from: base.yaml\nmetadata: {}\n" });
    mockSyncConfig.mockRejectedValueOnce(new Error("dirty from: leaf"));

    await expect(useConfigStore.getState().syncYaml()).rejects.toThrow("dirty from: leaf");

    expect(useConfigStore.getState().dirty).toBe(true);
  });
});
