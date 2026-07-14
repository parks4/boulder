/**
 * Asserts deriveMode: explicit mode wins, otherwise derived from kind, and
 * an unset/unknown kind defaults to "steady".
 */

import { describe, it, expect } from "vitest";
import { deriveMode, KIND_DOC_URLS, STEADY_KINDS, TRANSIENT_KINDS } from "./solverShared";

describe("deriveMode", () => {
  it("defaults to steady when neither kind nor mode is set", () => {
    expect(deriveMode(undefined)).toBe("steady");
  });

  it("derives transient from a transient kind", () => {
    expect(deriveMode("advance_grid")).toBe("transient");
    expect(deriveMode("micro_step")).toBe("transient");
    expect(deriveMode("advance")).toBe("transient");
  });

  it("derives steady from a steady kind", () => {
    expect(deriveMode("advance_to_steady_state")).toBe("steady");
    expect(deriveMode("solve_steady")).toBe("steady");
  });

  it("falls back to steady for an unrecognized kind", () => {
    expect(deriveMode("some_unknown_kind")).toBe("steady");
  });

  it("prefers an explicit mode over the kind-derived one", () => {
    expect(deriveMode("advance", "steady")).toBe("steady");
    expect(deriveMode("advance_to_steady_state", "transient")).toBe("transient");
  });
});

describe("KIND_DOC_URLS", () => {
  it("has a Cantera doc entry for every steady and transient kind", () => {
    for (const kind of [...STEADY_KINDS, ...TRANSIENT_KINDS]) {
      expect(KIND_DOC_URLS[kind]).toBeDefined();
      expect(KIND_DOC_URLS[kind].docUrl).toMatch(/^https:\/\/cantera\.org\//);
      expect(KIND_DOC_URLS[kind].description.length).toBeGreaterThan(0);
    }
  });
});
