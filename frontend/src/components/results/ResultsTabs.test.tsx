/**
 * Vitest unit tests for ResultsTabs default tab selection.
 *
 * Asserts that when final results lack Sankey data the Plots tab is shown by
 * default (not an empty Sankey pane), and that a reactor node is auto-selected
 * so plot content can render without an extra click.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { SimulationResults } from "@/types/simulation";

const mockSetSelectedElement = vi.fn();
let mockResults: SimulationResults | null = null;
let mockProgress: SimulationResults | null = null;
let mockIsRunning = false;
let mockActiveTab: string | null = null;
let mockSelectedElement: { type: string; data: Record<string, unknown> } | null = null;

const baseResults: SimulationResults = {
  is_running: false,
  is_complete: true,
  times: [0, 1],
  reactors_series: {
    reactor1: { T: [300, 400], P: [101325, 101325], X: { N2: [0.8, 0.7] } },
  },
  sankey_links: null,
  sankey_nodes: null,
};

vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: (selector: (s: unknown) => unknown) =>
    selector({
      results: mockResults,
      progress: mockProgress,
      isRunning: mockIsRunning,
      error: null,
    }),
}));

vi.mock("@/stores/selectionStore", () => ({
  useSelectionStore: (selector: (s: unknown) => unknown) =>
    selector({
      selectedElement: mockSelectedElement,
      setSelectedElement: mockSetSelectedElement,
    }),
}));

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({
      config: {
        nodes: [{ id: "reactor1", type: "IdealGasReactor", properties: {} }],
        connections: [],
      },
    }),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: unknown) => unknown) =>
    selector({ theme: "light" }),
}));

vi.mock("@/stores/resultsTabStore", () => ({
  useResultsTabStore: (selector: (s: unknown) => unknown) =>
    selector({
      activeTab: mockActiveTab,
      setActiveTab: vi.fn(),
    }),
}));

vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: (selector: (s: unknown) => unknown) =>
    selector({ activeId: null }),
}));

vi.mock("@/stores/sweepStore", () => ({
  useSweepRunStore: (selector: (s: unknown) => unknown) =>
    selector({ scenarioProgress: {} }),
}));

vi.mock("@/api/plugins", () => ({
  fetchPlugins: vi.fn().mockResolvedValue([]),
  renderPlugin: vi.fn(),
}));

vi.mock("./PlotsTab", () => ({
  PlotsTab: () => <div data-testid="plots-tab" />,
}));

vi.mock("./ConvergenceTab", () => ({
  ConvergenceTab: () => null,
}));

vi.mock("./SummaryTab", () => ({
  SummaryTab: () => null,
}));

vi.mock("./ErrorTab", () => ({
  ErrorTab: () => null,
}));

vi.mock("./PluginTab", () => ({
  PluginTab: () => null,
}));

vi.mock("./SweepCalculatingCard", () => ({
  SweepCalculatingCard: () => null,
}));

vi.mock("./SimulationCalculatingCard", () => ({
  SimulationCalculatingCard: () => <div data-testid="simulation-calculating-card" />,
}));

vi.mock("./SankeyTab", () => ({
  SankeyTab: () => <div data-testid="sankey-tab" />,
}));

vi.mock("./ThermoReportTab", () => ({
  ThermoReportTab: () => null,
}));

import { ResultsTabs } from "./ResultsTabs";

describe("ResultsTabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockResults = null;
    mockProgress = null;
    mockIsRunning = false;
    mockActiveTab = null;
    mockSelectedElement = null;
  });

  it("shows the non-blocking calculating card while a plain Run Simulation is in progress", () => {
    mockIsRunning = true;

    render(<ResultsTabs />);

    expect(screen.getByTestId("simulation-calculating-card")).toBeInTheDocument();
    expect(screen.queryByTestId("plots-tab")).not.toBeInTheDocument();
  });

  it("defaults to Plots when results have no Sankey data", () => {
    mockResults = { ...baseResults };

    render(<ResultsTabs />);

    expect(screen.getByRole("button", { name: "Plots" })).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("plots-tab")).toBeInTheDocument();
    expect(screen.queryByTestId("sankey-tab")).not.toBeInTheDocument();
  });

  it("defaults to Sankey when Sankey data is present", async () => {
    mockResults = {
      ...baseResults,
      sankey_links: { source: [0], target: [1], value: [1] },
      sankey_nodes: ["in", "out"],
    };

    render(<ResultsTabs />);

    expect(screen.getByRole("button", { name: "Sankey" })).toHaveAttribute(
      "data-active",
      "true",
    );
    await waitFor(() => {
      expect(screen.getByTestId("sankey-tab")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("plots-tab")).not.toBeInTheDocument();
  });

  it("auto-selects a reactor when Sankey is missing and nothing is selected", async () => {
    mockResults = { ...baseResults };

    render(<ResultsTabs />);

    await waitFor(() => {
      expect(mockSetSelectedElement).toHaveBeenCalledWith({
        type: "node",
        data: { id: "reactor1", type: "IdealGasReactor" },
      });
    });
  });
});
