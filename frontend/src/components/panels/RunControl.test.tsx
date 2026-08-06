/**
 * Asserts RunControl split-button modes: Run Simulation, Force Run, and Run Sweep.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { RunControl } from "./RunControl";
import { useSweepRunStore } from "@/stores/sweepStore";
import { useSimulationStore } from "@/stores/simulationStore";

const mockGetSweepInfo = vi
  .fn()
  .mockResolvedValue({ can_run: false, reason: "No sweep" });
const mockStartSweep = vi.fn();
const mockGetSweepStatus = vi.fn();
vi.mock("@/api/sweep", () => ({
  getSweepInfo: (...args: unknown[]) => mockGetSweepInfo(...args),
  getSweepStatus: (...args: unknown[]) => mockGetSweepStatus(...args),
  startSweep: (...args: unknown[]) => mockStartSweep(...args),
}));

const mockToastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: (...args: unknown[]) => mockToastInfo(...args) },
}));

let mockScenarioRevision = 0;
let mockAuthoredIdsLength = 0;
const mockRefresh = vi.fn();
vi.mock("@/stores/scenarioStore", () => {
  // sweepStore (a real module, exercised via useSweepRunStore below) reads
  // this through the static `.getState()` accessor, not the selector-hook
  // call form the rest of this test file uses -- both need to work.
  const state = () => ({
    refresh: mockRefresh,
    revision: mockScenarioRevision,
    overlays: {},
    authoredIds: Array.from({ length: mockAuthoredIdsLength }, (_, i) => String(i)),
  });
  const hook = (selector: (s: unknown) => unknown) => selector(state());
  hook.getState = state;
  return { useScenarioStore: hook };
});

describe("RunControl", () => {
  const onRunSimulation = vi.fn();
  const onStopSimulation = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSweepInfo.mockResolvedValue({ can_run: false, reason: "No sweep" });
    mockScenarioRevision = 0;
    mockAuthoredIdsLength = 0;
    useSweepRunStore.setState({
      sweeping: false,
      stopping: false,
      progress: { current: 0, total: 0 },
    });
    useSimulationStore.setState({ isRunning: false, progress: null });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows Force Run in the menu and switches the primary label without Ctrl+Enter", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        onStopSimulation={onStopSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByLabelText("Choose run action"));
    expect(screen.getByRole("menuitemradio", { name: /force run/i })).toBeInTheDocument();
    expect(screen.getByText("Solve ignoring cache")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitemradio", { name: /force run/i }));
    expect(screen.getByRole("button", { name: "Force Run" })).toBeInTheDocument();
    expect(screen.queryByText(/ctrl\+enter/i)).not.toBeInTheDocument();
  });

  it("calls onRunSimulation(true) when Force Run mode is selected and primary is clicked", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        onStopSimulation={onStopSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByLabelText("Choose run action"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /force run/i }));
    fireEvent.click(screen.getByRole("button", { name: "Force Run" }));

    expect(onRunSimulation).toHaveBeenCalledOnce();
    expect(onRunSimulation).toHaveBeenCalledWith(true);
  });

  it("calls onRunSimulation(false) for the default Run Simulation mode", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        onStopSimulation={onStopSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /run simulation/i }));
    expect(onRunSimulation).toHaveBeenCalledWith(false);
  });

  it("nudges toward Ctrl+Enter after repeatedly clicking Run Simulation by mouse", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        onStopSimulation={onStopSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    const button = screen.getByRole("button", { name: /run simulation/i });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mockToastInfo).not.toHaveBeenCalled();

    fireEvent.click(button);
    expect(mockToastInfo).toHaveBeenCalledOnce();
    expect(mockToastInfo).toHaveBeenCalledWith(expect.stringContaining("Ctrl+Enter"));
  });

  it("does not nudge while in Force Run mode, since Ctrl+Enter doesn't do the same thing", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        onStopSimulation={onStopSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByLabelText("Choose run action"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /force run/i }));
    const button = screen.getByRole("button", { name: "Force Run" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    expect(mockToastInfo).not.toHaveBeenCalled();
  });

  it("clicking Run Sweep starts a sweep via the shared sweep-run store", async () => {
    mockGetSweepInfo.mockResolvedValue({
      can_run: true,
      n_scenarios: 2,
      reason: "Run 2 scenarios",
    });
    render(
      <RunControl onRunSimulation={onRunSimulation} onStopSimulation={onStopSimulation} isRunning={false} runDisabled={false} />,
    );
    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalled());

    fireEvent.click(screen.getByLabelText("Choose run action"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /run sweep/i }));

    vi.useFakeTimers();
    try {
      mockStartSweep.mockResolvedValue({ status: "running", total: 2 });
      mockGetSweepStatus.mockResolvedValueOnce({ status: "done", current: 2, total: 2 });

      fireEvent.click(screen.getByRole("button", { name: /run sweep/i }));

      expect(mockStartSweep).toHaveBeenCalledWith({ scenarios: {}, noCache: undefined });
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(1000);
    } finally {
      vi.useRealTimers();
    }
  });

  it("enables Run Sweep from a session-created scenario even before the backend's snapshot catches up", async () => {
    // Scenario authoring is in-memory now (scenarioStore.overlays) -- a
    // scenario created this session isn't reflected in getSweepInfo's
    // startup-snapshot-based response until a reload, so the live
    // authoredIds count must be able to enable the button on its own.
    mockGetSweepInfo.mockResolvedValue({ can_run: false, reason: "No sweep" });
    mockAuthoredIdsLength = 2; // BASELINE + one session-created scenario
    render(
      <RunControl onRunSimulation={onRunSimulation} onStopSimulation={onStopSimulation} isRunning={false} runDisabled={false} />,
    );
    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalled());

    fireEvent.click(screen.getByLabelText("Choose run action"));
    expect(screen.getByRole("menuitemradio", { name: /run sweep/i })).not.toBeDisabled();
  });

  it("re-fetches sweep info when a scenario is added/edited/renamed/deleted elsewhere", async () => {
    const { rerender } = render(
      <RunControl onRunSimulation={onRunSimulation} onStopSimulation={onStopSimulation} isRunning={false} runDisabled={false} />,
    );
    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalledOnce());

    mockGetSweepInfo.mockResolvedValue({ can_run: true, n_scenarios: 3, reason: "Run 3 scenarios" });
    mockScenarioRevision += 1;
    rerender(
      <RunControl onRunSimulation={onRunSimulation} onStopSimulation={onStopSimulation} isRunning={false} runDisabled={false} />,
    );

    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalledTimes(2));
  });

  describe("Stop / Stopping", () => {
    it("shows Stop Simulation (destructive) while a single run is active", () => {
      useSimulationStore.setState({ isRunning: true, progress: null });
      render(
        <RunControl
          onRunSimulation={onRunSimulation}
          onStopSimulation={onStopSimulation}
          isRunning={true}
          runDisabled={true}
        />,
      );

      const button = screen.getByRole("button", { name: "Stop Simulation" });
      expect(button).not.toBeDisabled();
    });

    it("clicking Stop Simulation while running calls onStopSimulation, not onRunSimulation", () => {
      useSimulationStore.setState({ isRunning: true, progress: null });
      render(
        <RunControl
          onRunSimulation={onRunSimulation}
          onStopSimulation={onStopSimulation}
          isRunning={true}
          runDisabled={true}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "Stop Simulation" }));

      expect(onStopSimulation).toHaveBeenCalledOnce();
      expect(onRunSimulation).not.toHaveBeenCalled();
    });

    it("shows a disabled Stopping Simulation… once is_stopping is set, with a checkpoint tooltip", () => {
      useSimulationStore.setState({
        isRunning: true,
        // @ts-expect-error -- partial SimulationProgress is fine for this test
        progress: { is_stopping: true },
      });
      render(
        <RunControl
          onRunSimulation={onRunSimulation}
          onStopSimulation={onStopSimulation}
          isRunning={true}
          runDisabled={true}
        />,
      );

      const button = screen.getByRole("button", { name: "Stopping Simulation…" });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Will stop at the next checkpoint");
    });

    it("regression: disables the primary button while stopping even if the caller's runDisabled prop is false", () => {
      // RunControl must not rely on the caller to compute this correctly --
      // is_stopping alone must be enough to keep the button inert.
      useSimulationStore.setState({
        isRunning: true,
        // @ts-expect-error -- partial SimulationProgress is fine for this test
        progress: { is_stopping: true },
      });
      render(
        <RunControl
          onRunSimulation={onRunSimulation}
          onStopSimulation={onStopSimulation}
          isRunning={true}
          runDisabled={false}
        />,
      );

      expect(screen.getByRole("button", { name: "Stopping Simulation…" })).toBeDisabled();
    });

    // The caret (used to switch to "Run Sweep" mode) is disabled once
    // `sweeping` is true, so each test below selects sweep mode first --
    // while idle -- and only then mutates the store to simulate the sweep
    // having started; RunControl's own `runMode` state stays "sweep" across
    // that later store update, no further menu interaction needed.
    async function renderInSweepMode() {
      mockGetSweepInfo.mockResolvedValue({
        can_run: true,
        n_scenarios: 3,
        reason: "Run 3 scenarios",
      });
      render(
        <RunControl
          onRunSimulation={onRunSimulation}
          onStopSimulation={onStopSimulation}
          isRunning={false}
          runDisabled={false}
        />,
      );
      await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalled());
      fireEvent.click(screen.getByLabelText("Choose run action"));
      // getSweepInfo resolves asynchronously -- `canSweep` (and so the menu
      // item's disabled state) may not have caught up yet even though the
      // call itself already happened; a click on a still-disabled item is a
      // silent no-op, so wait for it to actually be enabled first.
      await waitFor(() =>
        expect(screen.getByRole("menuitemradio", { name: /run sweep/i })).not.toBeDisabled(),
      );
      fireEvent.click(screen.getByRole("menuitemradio", { name: /run sweep/i }));
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Run Sweep (3 scenarios)" })).toBeInTheDocument(),
      );
    }

    it("shows Stop Sweep (n/total) while a sweep is running", async () => {
      await renderInSweepMode();
      act(() => {
        useSweepRunStore.setState({
          sweeping: true,
          stopping: false,
          progress: { current: 1, total: 3 },
        });
      });

      expect(screen.getByRole("button", { name: "Stop Sweep (1/3)" })).not.toBeDisabled();
    });

    it("clicking Stop Sweep calls the sweep store's stop(), not onRunSimulation", async () => {
      await renderInSweepMode();
      const mockStop = vi.fn();
      act(() => {
        useSweepRunStore.setState({
          sweeping: true,
          stopping: false,
          progress: { current: 1, total: 3 },
          stop: mockStop,
        });
      });

      fireEvent.click(screen.getByRole("button", { name: "Stop Sweep (1/3)" }));

      expect(mockStop).toHaveBeenCalledOnce();
      expect(onRunSimulation).not.toHaveBeenCalled();
    });

    it("shows a disabled Stopping Sweep… once the sweep store reports stopping", async () => {
      await renderInSweepMode();
      act(() => {
        useSweepRunStore.setState({
          sweeping: true,
          stopping: true,
          progress: { current: 1, total: 3 },
        });
      });

      expect(screen.getByRole("button", { name: "Stopping Sweep…" })).toBeDisabled();
    });
  });
});
