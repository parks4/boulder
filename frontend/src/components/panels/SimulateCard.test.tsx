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
import { useSweepRunStore } from "@/stores/sweepStore";
import { useScenarioStore } from "@/stores/scenarioStore";

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
  // Not cached by default, so the Run-button tests exercise the real
  // startSimulation path rather than the early-return cache hit. Previously
  // this resolved `cached: true` unconditionally, and the tests only passed
  // because the old useSimulationStore mock omitted `setResults` -- calling
  // it in the cache-hit branch threw, was swallowed by handleRun's own
  // try/catch, and fell through to startSimulation by accident.
  checkSimulationCache: vi.fn().mockResolvedValue({
    cached: false,
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
  toast: { error: vi.fn(), success: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/api/sweep", () => ({
  getSweepInfo: vi.fn().mockResolvedValue({ n_scenarios: 4 }),
}));

import { toast } from "sonner";

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

vi.mock("@/stores/simulationStore", () => {
  // Mirrors zustand's real call shape: `useSimulationStore()` (no selector,
  // used by SimulateCard's own destructuring) and `useSimulationStore(sel)`
  // (used by RunControl's useRunStatus hook, via useSimulationRunPhase) must
  // both work — a mock that ignored the selector previously returned this
  // whole (truthy) object for `progress?.is_stopping`, always reading as
  // "stopping".
  const state = {
    isRunning: false,
    simulationId: null,
    progress: null,
    pythonCode: "",
    beginSimulationRun: vi.fn(),
    startSimulation: vi.fn(),
    setError: vi.fn(),
    setResults: vi.fn(),
    stopped: vi.fn(),
  };
  const useSimulationStore = (selector?: (s: typeof state) => unknown) =>
    selector ? selector(state) : state;
  return { useSimulationStore };
});

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
    useSweepRunStore.setState({ sweeping: false });
    useScenarioStore.setState({ activeId: null, overlays: {} });
  });

  it("sends the authored overlays even when running BASELINE (no scenario selected)", async () => {
    // Regression: the server's `_merged_raw` uses the overlays map's presence
    // to tell whether the base config declares `scenarios:` at all, naming
    // the stored base entry BASELINE vs BASE accordingly (see
    // `runset.base_entry_id`). Omitting overlays for a plain BASELINE run
    // used to make that result land under the wrong name -- a phantom row
    // next to the real (still "Not computed yet") BASELINE one.
    mockConfig = { nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }], connections: [] };
    useScenarioStore.setState({ activeId: null, overlays: { hot: { metadata: {} } } });
    render(<SimulateCard />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /run simulation/i }));
    });
    expect(mockStartSimulation).toHaveBeenCalledOnce();
    const [, , , scenario] = mockStartSimulation.mock.calls[0];
    expect(scenario).toEqual({ id: "BASELINE", overlays: { hot: { metadata: {} } } });
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
      { id: "report", label: "Export Report", requires_simulation: false, is_available: true },
    ]);
    render(<SimulateCard />);
    await act(async () => {});
    mockSyncYaml.mockClear();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /export report/i }));
    });

    expect(mockSyncYaml).toHaveBeenCalled();
    expect(mockRunGuiAction).toHaveBeenCalledOnce();
  });

  it("shows a scenario-count ETA for any action declaring estimated_seconds_per_scenario", async () => {
    // Deliberately not the network-image action's id/label — this must be driven
    // purely by the generic field, with no plugin-specific knowledge here.
    mockFetchGuiActions.mockResolvedValueOnce([
      {
        id: "some_other_plugin_action",
        label: "Some Other Export",
        requires_simulation: true,
        is_available: true,
        estimated_seconds_per_scenario: 5,
      },
    ]);
    render(<SimulateCard />);
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /some other export/i }));
    });

    expect(toast.loading).toHaveBeenCalledWith(
      expect.stringContaining('"Some Other Export"'),
      expect.objectContaining({ id: "some_other_plugin_action" }),
    );
    expect(toast.loading).toHaveBeenCalledWith(
      expect.stringMatching(/4 scenarios.*~20s expected/),
      expect.anything(),
    );
    // The success toast replaces the same estimate rather than stacking.
    expect(toast.success).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: "some_other_plugin_action" }),
    );
  });

  it("does not show a scenario-count ETA for an action with no estimate", async () => {
    mockFetchGuiActions.mockResolvedValueOnce([
      { id: "other_action", label: "Some Other Export", requires_simulation: false, is_available: true },
    ]);
    render(<SimulateCard />);
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /some other export/i }));
    });

    expect(toast.loading).not.toHaveBeenCalled();
  });

  it("regression: disables the Run button while a sweep is running", () => {
    // A plain run and a sweep share the same backend solve path and must
    // not overlap -- runDisabled previously only checked isRunning, so a
    // sweep in progress didn't stop a second, conflicting solve from being
    // launched on top of it.
    mockConfig = { nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }], connections: [] };
    useSweepRunStore.setState({ sweeping: true });
    render(<SimulateCard />);

    expect(screen.getByRole("button", { name: /run simulation/i })).toBeDisabled();
  });
});
