/**
 * Vitest unit tests for the AppShell header and sidebar wiring.
 *
 * Asserts:
 * - The header no longer shows a filename button or solver-mode badge
 *   (moved into NetworkCard / removed as redundant with the Simulate toggle).
 * - The left sidebar renders NetworkCard, SimulateCard, and PropertiesPanel.
 * - AddReactorModal/AddMFCModal read their open state from addEntityModalStore,
 *   so right-click-on-graph and Stage-panel triggers reach the same modal.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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

vi.mock("@/components/panels/NetworkCard", () => ({
  NetworkCard: ({ onEditYaml }: { onEditYaml: () => void }) => (
    <div data-testid="network-card">
      <button onClick={onEditYaml}>Edit YAML</button>
    </div>
  ),
}));

vi.mock("@/components/panels/SimulateCard", () => ({
  SimulateCard: () => <div data-testid="simulate-card" />,
}));

vi.mock("@/components/panels/PropertiesPanel", () => ({
  PropertiesPanel: () => <div data-testid="properties-panel" />,
}));

vi.mock("@/components/panels/YamlPane", () => ({
  YamlPane: () => <div data-testid="yaml-pane" />,
}));

vi.mock("@/components/panels/ScenarioPane", () => ({
  ScenarioPane: () => <div data-testid="scenario-pane" />,
}));

let mockScenariosAvailable = false;
let mockAuthoredScenarioIds: string[] = [];
const mockRefreshScenarios = vi.fn();

vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: (selector: (s: unknown) => unknown) =>
    selector({
      available: mockScenariosAvailable,
      authoredIds: mockAuthoredScenarioIds,
      refresh: mockRefreshScenarios,
    }),
}));

let mockYamlPaneOpen = false;
const mockOpenYamlPane = vi.fn();

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: () => ({
    leftCollapsed: false,
    rightCollapsed: false,
    leftWidth: 320,
    rightWidth: 250,
    toggleLeft: vi.fn(),
    yamlPaneOpen: mockYamlPaneOpen,
    yamlWidth: 420,
    openYamlPane: mockOpenYamlPane,
    closeYamlPane: vi.fn(),
  }),
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

let mockReactorModal: { open: boolean; group?: string | null } = { open: false };
let mockConnectionModal: { open: boolean; group?: string | null; source?: string } = {
  open: false,
};
const mockCloseAddReactor = vi.fn();
const mockCloseAddConnection = vi.fn();

vi.mock("@/components/modals/AddReactorModal", () => ({
  AddReactorModal: ({ open, defaultGroup }: { open: boolean; defaultGroup?: string | null }) =>
    open ? <div data-testid="add-reactor-modal">{defaultGroup ?? ""}</div> : null,
}));

vi.mock("@/components/modals/AddMFCModal", () => ({
  AddMFCModal: ({
    open,
    defaultSource,
  }: {
    open: boolean;
    defaultSource?: string;
  }) => (open ? <div data-testid="add-mfc-modal">{defaultSource ?? ""}</div> : null),
}));

vi.mock("@/stores/addEntityModalStore", () => ({
  useAddEntityModalStore: () => ({
    reactorModal: mockReactorModal,
    connectionModal: mockConnectionModal,
    closeAddReactor: mockCloseAddReactor,
    closeAddConnection: mockCloseAddConnection,
  }),
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

describe("AppShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig = { nodes: [], connections: [] };
    mockReactorModal = { open: false };
    mockConnectionModal = { open: false };
    mockYamlPaneOpen = false;
    mockScenariosAvailable = false;
    mockAuthoredScenarioIds = [];
  });

  it("renders the sidebar cards but no header filename button or solver badge", () => {
    render(<AppShell />);

    expect(screen.getByTestId("network-card")).toBeInTheDocument();
    expect(screen.getByTestId("simulate-card")).toBeInTheDocument();
    expect(screen.getByTestId("properties-panel")).toBeInTheDocument();

    expect(screen.queryByTestId("solver-mode-badge")).not.toBeInTheDocument();
    expect(screen.queryByText("test.yaml")).not.toBeInTheDocument();
  });

  it("does not render the Add Reactor modal when the store says it's closed", () => {
    render(<AppShell />);
    expect(screen.queryByTestId("add-reactor-modal")).not.toBeInTheDocument();
  });

  it("renders the Add Reactor modal, pre-filled with its stage, when the store opens it", () => {
    mockReactorModal = { open: true, group: "psr_stage" };
    render(<AppShell />);
    expect(screen.getByTestId("add-reactor-modal")).toHaveTextContent("psr_stage");
  });

  it("renders the Add Connection modal, pre-filled with its source, when the store opens it", () => {
    mockConnectionModal = { open: true, source: "torch" };
    render(<AppShell />);
    expect(screen.getByTestId("add-mfc-modal")).toHaveTextContent("torch");
  });

  it("does not render the YAML pane when the layout store says it's closed", () => {
    render(<AppShell />);
    expect(screen.queryByTestId("yaml-pane")).not.toBeInTheDocument();
  });

  it("renders the YAML pane when the layout store says it's open", () => {
    mockYamlPaneOpen = true;
    render(<AppShell />);
    expect(screen.getByTestId("yaml-pane")).toBeInTheDocument();
  });

  it("clicking Edit YAML in the Network card opens the YAML pane", () => {
    render(<AppShell />);
    screen.getByRole("button", { name: "Edit YAML" }).click();
    expect(mockOpenYamlPane).toHaveBeenCalledOnce();
  });

  it("does not render the Scenario pane when there's no store and no authored scenarios", () => {
    render(<AppShell />);
    expect(screen.queryByTestId("scenario-pane")).not.toBeInTheDocument();
  });

  it("renders the Scenario pane once a scenario store exists", () => {
    mockScenariosAvailable = true;
    render(<AppShell />);
    expect(screen.getByTestId("scenario-pane")).toBeInTheDocument();
  });

  it("renders the Scenario pane for authored-but-not-yet-swept scenarios even without a store", () => {
    mockAuthoredScenarioIds = ["draft_a"];
    render(<AppShell />);
    expect(screen.getByTestId("scenario-pane")).toBeInTheDocument();
  });
});
