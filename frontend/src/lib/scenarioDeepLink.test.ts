/**
 * Vitest unit tests for the ``/?scenario=<id>`` deep link.
 *
 * Asserts:
 * - an id present in the loaded config is selected (ids with "/" and "=" included);
 * - an absent id shows a message and selects nothing;
 * - the parameter is removed from the URL after use, other parameters kept.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

const mockReset = vi.fn().mockResolvedValue(undefined);
const mockSetActive = vi.fn().mockResolvedValue(undefined);
let mockState: { authoredIds: string[]; scenarios: { id: string }[] };

vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: {
    getState: () => ({ ...mockState, resetForNewConfig: mockReset, setActive: mockSetActive }),
  },
}));
const mockToastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (m: string) => mockToastError(m) } }));

import { applyScenarioDeepLink } from "./scenarioDeepLink";

describe("applyScenarioDeepLink", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState = { authoredIds: ["baseline", "a/b=c"], scenarios: [{ id: "swept" }] };
    window.history.replaceState(null, "", "/");
  });

  it("selects a scenario present in the loaded config, decoding the id", async () => {
    window.history.replaceState(null, "", "/?scenario=" + encodeURIComponent("a/b=c"));
    await applyScenarioDeepLink();
    expect(mockSetActive).toHaveBeenCalledWith("a/b=c");
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("selects a computed scenario even when it has no authored overlay", async () => {
    window.history.replaceState(null, "", "/?scenario=swept");
    await applyScenarioDeepLink();
    expect(mockSetActive).toHaveBeenCalledWith("swept");
  });

  it("shows a message and selects nothing for an unknown id", async () => {
    window.history.replaceState(null, "", "/?scenario=nope");
    await applyScenarioDeepLink();
    expect(mockSetActive).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith(expect.stringContaining("nope"));
  });

  it("removes the parameter after use but keeps the others", async () => {
    window.history.replaceState(null, "", "/?x=1&scenario=nope");
    await applyScenarioDeepLink();
    expect(window.location.search).toBe("?x=1");
  });

  it("does nothing without the parameter", async () => {
    await applyScenarioDeepLink();
    expect(mockReset).not.toHaveBeenCalled();
    expect(mockSetActive).not.toHaveBeenCalled();
  });
});
