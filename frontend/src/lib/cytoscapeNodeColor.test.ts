/**
 * Vitest unit tests for cytoscapeNodeColor helpers.
 *
 * Asserts:
 * - Cold and hot ends of the scale match Cytoscape stylesheet endpoints.
 * - Missing reactor reports fall back to the cold-end default.
 */

import { describe, expect, it } from "vitest";
import {
  CYTOSCAPE_TEMP_MAX_K,
  CYTOSCAPE_TEMP_MIN_K,
  mapSankeyNodeColors,
  temperatureToNodeColor,
} from "./cytoscapeNodeColor";

describe("cytoscapeNodeColor", () => {
  it("maps cold and hot temperatures to Cytoscape light-theme endpoints", () => {
    expect(temperatureToNodeColor(CYTOSCAPE_TEMP_MIN_K, "light")).toBe("#00bfff");
    expect(temperatureToNodeColor(CYTOSCAPE_TEMP_MAX_K, "light")).toBe("#ff6347");
  });

  it("maps cold and hot temperatures to Cytoscape dark-theme endpoints", () => {
    expect(temperatureToNodeColor(CYTOSCAPE_TEMP_MIN_K, "dark")).toBe("#4a90e2");
    expect(temperatureToNodeColor(CYTOSCAPE_TEMP_MAX_K, "dark")).toBe("#e94b3c");
  });

  it("uses the cold-end color when no temperature is available for a node", () => {
    const colors = mapSankeyNodeColors(["unknown"], undefined, undefined, "light");
    expect(colors).toEqual([temperatureToNodeColor(CYTOSCAPE_TEMP_MIN_K, "light")]);
  });
});
