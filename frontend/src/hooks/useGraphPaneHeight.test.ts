/**
 * Asserts graph pane height helpers clamp stored values within min/max bounds.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  DEFAULT_GRAPH_HEIGHT,
  MIN_GRAPH_HEIGHT,
  getMaxGraphHeight,
  loadStoredGraphHeight,
} from "./useGraphPaneHeight";

describe("useGraphPaneHeight helpers", () => {
  const storage = new Map<string, string>();

  beforeEach(() => {
    storage.clear();
    vi.stubGlobal("window", { innerHeight: 1000 });
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      clear: () => storage.clear(),
    });
  });

  it("returns default height when nothing is stored", () => {
    expect(loadStoredGraphHeight()).toBe(DEFAULT_GRAPH_HEIGHT);
  });

  it("clamps stored height to the viewport-based maximum", () => {
    localStorage.setItem("boulder-graph-height", "5000");
    expect(loadStoredGraphHeight()).toBe(getMaxGraphHeight());
    expect(getMaxGraphHeight()).toBe(1000 - 160);
  });

  it("clamps stored height to the minimum", () => {
    localStorage.setItem("boulder-graph-height", "50");
    expect(loadStoredGraphHeight()).toBe(MIN_GRAPH_HEIGHT);
  });
});
