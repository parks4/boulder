/**
 * Asserts RunControl split-button modes: Run Simulation, Force Run, and Run Sweep.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { RunControl } from "./RunControl";
import { useSweepRunStore } from "@/stores/sweepStore";

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

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSweepInfo.mockResolvedValue({ can_run: false, reason: "No sweep" });
    mockScenarioRevision = 0;
    mockAuthoredIdsLength = 0;
    useSweepRunStore.setState({ sweeping: false, progress: { current: 0, total: 0 } });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows Force Run in the menu and switches the primary label without Ctrl+Enter", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
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
      <RunControl onRunSimulation={onRunSimulation} isRunning={false} runDisabled={false} />,
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
      <RunControl onRunSimulation={onRunSimulation} isRunning={false} runDisabled={false} />,
    );
    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalled());

    fireEvent.click(screen.getByLabelText("Choose run action"));
    expect(screen.getByRole("menuitemradio", { name: /run sweep/i })).not.toBeDisabled();
  });

  it("re-fetches sweep info when a scenario is added/edited/renamed/deleted elsewhere", async () => {
    const { rerender } = render(
      <RunControl onRunSimulation={onRunSimulation} isRunning={false} runDisabled={false} />,
    );
    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalledOnce());

    mockGetSweepInfo.mockResolvedValue({ can_run: true, n_scenarios: 3, reason: "Run 3 scenarios" });
    mockScenarioRevision += 1;
    rerender(
      <RunControl onRunSimulation={onRunSimulation} isRunning={false} runDisabled={false} />,
    );

    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalledTimes(2));
  });
});
