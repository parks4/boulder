/**
 * Vitest unit tests for SimulateCard.
 *
 * Steady/Transient mode, Solver Details, and the stage-override banner now
 * live in StageCard (see StageCard.test.tsx) — SimulateCard only reads
 * mode/simTime/timeStep from the shared solver store to run a simulation.
 *
 * Asserts:
 * - startSimulation is called without simulation_time/time_step in steady mode.
 * - startSimulation is called with simulation_time/time_step in transient mode.
 * - Force Run skips the cache lookup and starts a fresh simulation.
 * - GUI actions sync YAML before fetching/running, so exports reflect GUI edits.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SimulateCard } from "./SimulateCard";
import { useSolverStore } from "@/stores/solverStore";

// ---------------------------------------------------------------------------
// Mock dependencies that reach out to the network or zustand stores
// ---------------------------------------------------------------------------

import { startSimulation } from "@/api/simulations";

vi.mock("@/api/simulations", () => ({
  startSimulation: vi.fn().mockResolvedValue({ simulation_id: "test-123" }),
}));

vi.mock("@/api/guiActions", () => ({
  fetchGuiActions: vi.fn().mockResolvedValue([]),
  runGuiAction: vi.fn().mockResolvedValue({ blob: new Blob(["x"]), filename: "note.xlsx" }),
}));

vi.mock("@/api/resultCache", () => ({
  checkSimulationCache: vi.fn().mockResolvedValue({
    cached: true,
    result: { time: [0], reactors: {} },
    meta: { created_at: Date.now() / 1000 },
  }),
}));

const mockStartSimulation = startSimulation as ReturnType<typeof vi.fn>;

import { checkSimulationCache } from "@/api/resultCache";
const mockCheckSimulationCache = checkSimulationCache as ReturnType<typeof vi.fn>;

import { fetchGuiActions, runGuiAction } from "@/api/guiActions";
const mockFetchGuiActions = fetchGuiActions as ReturnType<typeof vi.fn>;
const mockRunGuiAction = runGuiAction as ReturnType<typeof vi.fn>;

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const mockSetConfig = vi.fn();
const mockSyncYaml = vi.fn().mockResolvedValue(undefined);
let mockConfig: Record<string, unknown> = { nodes: [], connections: [] };

function configStoreState() {
  return {
    config: mockConfig,
    fileName: "test.yaml",
    originalYaml: "",
    dirty: false,
    setConfig: mockSetConfig,
    syncYaml: mockSyncYaml,
  };
}

vi.mock("@/stores/configStore", () => {
  const useConfigStore = (selector: (s: unknown) => unknown) =>
    selector(configStoreState());
  useConfigStore.getState = () => configStoreState();
  return { useConfigStore };
});

vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: () => ({
    isRunning: false,
    simulationId: null,
    pythonCode: "",
    beginSimulationRun: vi.fn(),
    startSimulation: vi.fn(),
    setError: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SimulateCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig = { nodes: [], connections: [] };
    useSolverStore.setState({
      mode: "steady",
      kind: "advance_to_steady_state",
      simTime: "10",
      timeStep: "1",
    });
  });

  it("Run button calls startSimulation without time/step in steady mode", async () => {
    mockConfig = { nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }], connections: [] };
    render(<SimulateCard />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run simulation/i }));
    });
    expect(mockStartSimulation).toHaveBeenCalledOnce();
    const [, simTime, timeStep] = mockStartSimulation.mock.calls[0];
    expect(simTime).toBeUndefined();
    expect(timeStep).toBeUndefined();
  });

  it("Run button calls startSimulation with time/step in transient mode", async () => {
    // Mode comes from config.settings.solver — SimulateCard's mount effect
    // syncs the shared solver store from it, so setting the store directly
    // (rather than via config) would just get overwritten on mount.
    mockConfig = {
      nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }],
      connections: [],
      settings: { solver: { mode: "transient", kind: "advance" } },
    };
    render(<SimulateCard />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run simulation/i }));
    });
    expect(mockStartSimulation).toHaveBeenCalledOnce();
    const [, simTime, timeStep] = mockStartSimulation.mock.calls[0];
    expect(typeof simTime).toBe("number");
    expect(typeof timeStep).toBe("number");
  });

  it("Force Run skips cache lookup and starts a fresh simulation", async () => {
    mockConfig = { nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }], connections: [] };
    render(<SimulateCard />);
    fireEvent.click(screen.getByLabelText("Choose run action"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /force run/i }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Force Run" }));
    });
    expect(mockCheckSimulationCache).not.toHaveBeenCalled();
    expect(mockStartSimulation).toHaveBeenCalledOnce();
  });

  it("syncs YAML before fetching GUI actions on mount", async () => {
    render(<SimulateCard />);
    await act(async () => {});
    expect(mockSyncYaml).toHaveBeenCalled();
    expect(mockFetchGuiActions).toHaveBeenCalled();
  });

  it("syncs YAML before running a GUI export action, so the export reflects GUI edits", async () => {
    mockFetchGuiActions.mockResolvedValueOnce([
      { id: "calc_note", label: "Export Calculation Note", requires_simulation: false, is_available: true },
    ]);
    render(<SimulateCard />);
    await act(async () => {});
    mockSyncYaml.mockClear();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /export calculation note/i }));
    });

    expect(mockSyncYaml).toHaveBeenCalled();
    expect(mockRunGuiAction).toHaveBeenCalledOnce();
  });
});
