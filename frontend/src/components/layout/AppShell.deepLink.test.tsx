/**
 * Vitest ordering tests for the scenario deep link inside AppShell's mount chain.
 *
 * Asserts:
 * - the deep link runs only after the cached-result chain has written the results
 *   store (so the scenario selection is the last write, never overwritten);
 * - it still runs, once, when no cached result exists or the cache fetch fails;
 * - it is not called when no preloaded config exists.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

const order: string[] = [];
const mockApplyDeepLink = vi.fn(async () => {
  order.push("deepLink");
});
const mockSetResults = vi.fn(() => order.push("setResults"));
const mockFetchPreloaded = vi.fn();
const mockFetchCached = vi.fn();

vi.mock("@/components/layout/HeaderStatus", () => ({ HeaderStatus: () => null }));
vi.mock("@/lib/scenarioDeepLink", () => ({ applyScenarioDeepLink: () => mockApplyDeepLink() }));
vi.mock("@/api/configs", () => ({
  fetchPreloadedConfig: () => mockFetchPreloaded(),
  fetchDefaultConfig: vi.fn().mockResolvedValue(null),
}));
vi.mock("@/api/resultCache", () => ({ fetchCachedResult: () => mockFetchCached() }));
vi.mock("@/api/simulations", () => ({ startSimulation: vi.fn() }));
vi.mock("@/hooks/useSimulationSSE", () => ({ useSimulationSSE: vi.fn() }));
vi.mock("@/hooks/useScenarioFocus", () => ({ useScenarioFocus: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: () => ({ theme: "light", toggleTheme: vi.fn() }),
}));
vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: () => ({
    isRunning: false,
    beginSimulationRun: vi.fn(),
    startSimulation: vi.fn(),
    setError: vi.fn(),
    setResults: mockSetResults,
  }),
}));
vi.mock("@/stores/configStore", () => {
  const state = { config: { nodes: [], connections: [] }, setConfig: vi.fn() };
  return { useConfigStore: Object.assign(() => state, { getState: () => state }) };
});
vi.mock("@/stores/addEntityModalStore", () => ({
  useAddEntityModalStore: () => ({
    reactorModal: { open: false },
    connectionModal: { open: false },
    closeAddReactor: vi.fn(),
    closeAddConnection: vi.fn(),
  }),
}));
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: () => ({
    leftCollapsed: false,
    rightCollapsed: false,
    leftWidth: 320,
    rightWidth: 250,
    toggleLeft: vi.fn(),
    yamlPaneOpen: false,
    yamlWidth: 420,
    openYamlPane: vi.fn(),
    scenarioYamlEditorId: null,
    closeScenarioYamlEditor: vi.fn(),
  }),
}));
vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: (selector: (s: unknown) => unknown) =>
    selector({ available: false, authoredIds: [], refresh: vi.fn(), activeId: null }),
}));
vi.mock("@/stores/sweepStore", () => ({
  useSweepRunStore: { getState: () => ({ hydrate: vi.fn() }) },
}));

const stub = vi.hoisted(() => () => null);
vi.mock("@/components/panels/NetworkCard", () => ({ NetworkCard: stub }));
vi.mock("@/components/panels/SimulateCard", () => ({ SimulateCard: stub }));
vi.mock("@/components/panels/PropertiesPanel", () => ({ PropertiesPanel: stub }));
vi.mock("@/components/panels/ScenarioPane", () => ({ ScenarioPane: stub }));
vi.mock("@/components/panels/YamlPane", () => ({ YamlPane: stub }));
vi.mock("@/components/panels/ScenarioYamlPane", () => ({ ScenarioYamlPane: stub }));
vi.mock("@/components/graph/ReactorGraph", () => ({ ReactorGraph: stub }));
vi.mock("@/components/results/ResultsTabs", () => ({ ResultsTabs: stub }));
vi.mock("@/components/modals/AddReactorModal", () => ({ AddReactorModal: stub }));
vi.mock("@/components/modals/AddMFCModal", () => ({ AddMFCModal: stub }));

import { AppShell } from "./AppShell";

const PRELOADED = { preloaded: true, config: { nodes: [], connections: [] }, filename: "m.yaml", yaml: "" };

describe("AppShell scenario deep link ordering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    order.length = 0;
    mockFetchPreloaded.mockResolvedValue(PRELOADED);
  });

  it("runs after the cached results are applied, not in parallel with them", async () => {
    let resolveCache!: (v: unknown) => void;
    mockFetchCached.mockReturnValue(new Promise((r) => (resolveCache = r)));
    render(<AppShell />);
    await waitFor(() => expect(mockFetchCached).toHaveBeenCalled());
    await Promise.resolve();
    expect(mockApplyDeepLink).not.toHaveBeenCalled();

    resolveCache({
      cached: true,
      result: {},
      meta: { created_at: Date.now() / 1000 },
    });
    await waitFor(() => expect(mockApplyDeepLink).toHaveBeenCalledOnce());
    expect(order).toEqual(["setResults", "deepLink"]);
  });

  it("runs when there is no cached result", async () => {
    mockFetchCached.mockResolvedValue({ cached: false });
    render(<AppShell />);
    await waitFor(() => expect(mockApplyDeepLink).toHaveBeenCalledOnce());
    expect(mockSetResults).not.toHaveBeenCalled();
  });

  it("runs when the cache fetch fails", async () => {
    mockFetchCached.mockRejectedValue(new Error("boom"));
    render(<AppShell />);
    await waitFor(() => expect(mockApplyDeepLink).toHaveBeenCalledOnce());
  });

  it("is not called without a preloaded config", async () => {
    mockFetchPreloaded.mockResolvedValue({ preloaded: false });
    render(<AppShell />);
    await waitFor(() => expect(mockFetchPreloaded).toHaveBeenCalled());
    await Promise.resolve();
    expect(mockApplyDeepLink).not.toHaveBeenCalled();
  });
});
