/**
 * Asserts configStore's `setOriginalYaml`: it replaces only the on-disk YAML
 * snapshot, leaving the live graph (`config`) and `dirty` flag untouched —
 * so an out-of-band disk write (e.g. scenario authoring) can refresh what
 * the YAML pane displays without discarding any unsaved node/connection
 * edits sitting in `config`.
 */

import { describe, it, expect, beforeEach } from "vitest";
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
});
