/**
 * Unit tests for Sankey availability helper.
 *
 * Asserts hasSankeyData is true only when both sankey_links and sankey_nodes
 * are present (non-null), matching what SankeyTab needs to render a diagram.
 */

import { describe, it, expect } from "vitest";
import { hasSankeyData } from "./sankeyData";

describe("hasSankeyData", () => {
  it("returns false when either links or nodes are missing", () => {
    expect(hasSankeyData({ sankey_links: null, sankey_nodes: null })).toBe(false);
    expect(hasSankeyData({ sankey_links: {}, sankey_nodes: null })).toBe(false);
    expect(hasSankeyData({ sankey_links: null, sankey_nodes: ["a"] })).toBe(false);
  });

  it("returns true when both links and nodes are present", () => {
    expect(
      hasSankeyData({
        sankey_links: { source: [0], target: [1], value: [1] },
        sankey_nodes: ["a", "b"],
      }),
    ).toBe(true);
  });
});
