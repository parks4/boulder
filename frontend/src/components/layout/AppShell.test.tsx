/**
 * Vitest unit tests for the AppShell Mode badge (Phase 0).
 *
 * Asserts:
 * - The mode badge reads "steady" when no solver is configured.
 * - The mode badge reads "transient" when config.settings.solver.kind is a transient kind.
 * - The mode badge reads "transient" when config.settings.solver.mode is "transient".
 * - The mode badge reads "steady" when config.settings.solver.kind is "solve_steady".
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// We need to mock all hooks/stores the AppShell component relies on
vi.mock("@/stores/themeStore", () => ({
  useThemeStore: () => ({ theme: "light", toggleTheme: vi.fn() }),
}));

vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: () => ({
    isRunning: false,
    beginSimulationRun: vi.fn(),
    startSimulation: vi.fn(),
    setError: vi.fn(),
  }),
}));

vi.mock("@/hooks/useSimulationSSE", () => ({
  useSimulationSSE: vi.fn(),
}));

vi.mock("@/hooks/useKeyboardShortcuts", () => ({
  useKeyboardShortcuts: vi.fn(),
}));

vi.mock("@/api/configs", () => ({
  fetchPreloadedConfig: vi.fn().mockResolvedValue({ preloaded: false }),
  fetchDefaultConfig: vi.fn().mockResolvedValue({ config: { nodes: [], connections: [] }, yaml: "" }),
}));

vi.mock("@/api/simulations", () => ({
  startSimulation: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/panels/EditNetworkCard", () => ({
  EditNetworkCard: () => <div data-testid="edit-network-card" />,
}));

vi.mock("@/components/panels/SimulateCard", () => ({
  SimulateCard: () => <div data-testid="simulate-card" />,
}));

vi.mock("@/components/panels/PropertiesPanel", () => ({
  PropertiesPanel: () => <div data-testid="properties-panel" />,
}));

vi.mock("@/components/graph/ReactorGraph", () => ({
  ReactorGraph: () => <div data-testid="reactor-graph" />,
}));

vi.mock("@/components/results/ResultsTabs", () => ({
  ResultsTabs: () => <div data-testid="results-tabs" />,
}));

vi.mock("@/components/simulation/SimulationOverlay", () => ({
  SimulationOverlay: () => <div data-testid="simulation-overlay" />,
}));

vi.mock("@/components/modals/YAMLEditorModal", () => ({
  YAMLEditorModal: () => <div data-testid="yaml-editor-modal" />,
}));

let mockConfig: Record<string, unknown> = { nodes: [], connections: [] };

vi.mock("@/stores/configStore", () => ({
  useConfigStore: () => ({
    config: mockConfig,
    fileName: "test.yaml",
    setConfig: vi.fn(),
  }),
}));

// Import AFTER mocks are set up
import { AppShell } from "./AppShell";

describe("AppShell Mode badge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig = { nodes: [], connections: [] };
  });

  it("shows 'steady' badge when no solver is configured", () => {
    render(<AppShell />);
    const badge = screen.getByTestId("solver-mode-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toMatch(/steady/i);
  });

  it("shows 'transient' badge when kind is advance_grid", () => {
    mockConfig = {
      nodes: [],
      connections: [],
      settings: { solver: { kind: "advance_grid" } },
    };
    render(<AppShell />);
    const badge = screen.getByTestId("solver-mode-badge");
    expect(badge.textContent).toMatch(/transient/i);
  });

  it("shows 'transient' badge when kind is micro_step", () => {
    mockConfig = {
      nodes: [],
      connections: [],
      settings: { solver: { kind: "micro_step" } },
    };
    render(<AppShell />);
    const badge = screen.getByTestId("solver-mode-badge");
    expect(badge.textContent).toMatch(/transient/i);
  });

  it("shows 'steady' badge when kind is solve_steady", () => {
    mockConfig = {
      nodes: [],
      connections: [],
      settings: { solver: { kind: "solve_steady" } },
    };
    render(<AppShell />);
    const badge = screen.getByTestId("solver-mode-badge");
    expect(badge.textContent).toMatch(/steady/i);
  });

  it("shows 'transient' badge when solver.mode is explicitly transient", () => {
    mockConfig = {
      nodes: [],
      connections: [],
      settings: { solver: { mode: "transient", kind: "advance" } },
    };
    render(<AppShell />);
    const badge = screen.getByTestId("solver-mode-badge");
    expect(badge.textContent).toMatch(/transient/i);
  });
});
