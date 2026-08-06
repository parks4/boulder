/**
 * Asserts the shared sweep-run store: starts a job, polls to completion,
 * refreshes scenarios and toasts on success/failure, passes `noCache`
 * through, and refuses a second job while one is already running. RunControl's
 * "Run Sweep" calls this single store instead of owning its own poll loop.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockStartSweep = vi.fn();
const mockGetSweepStatus = vi.fn();
const mockStopSweep = vi.fn();
vi.mock("@/api/sweep", () => ({
  startSweep: (...args: unknown[]) => mockStartSweep(...args),
  getSweepStatus: (...args: unknown[]) => mockGetSweepStatus(...args),
  stopSweep: (...args: unknown[]) => mockStopSweep(...args),
}));

const mockRefresh = vi.fn();
const mockSetActive = vi.fn();
let mockActiveId: string | null = null;
let mockScenarios: Array<{ id: string }> = [];
let mockOverlays: Record<string, unknown> = {};
vi.mock("./scenarioStore", () => ({
  useScenarioStore: {
    getState: () => ({
      refresh: mockRefresh,
      setActive: mockSetActive,
      overlays: mockOverlays,
      get activeId() {
        return mockActiveId;
      },
      get scenarios() {
        return mockScenarios;
      },
    }),
  },
}));

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
const mockToastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
    info: (...args: unknown[]) => mockToastInfo(...args),
  },
}));

import { useSweepRunStore } from "./sweepStore";

describe("sweepStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockActiveId = null;
    mockScenarios = [];
    mockOverlays = {};
    useSweepRunStore.setState({
      sweeping: false,
      stopping: false,
      progress: { current: 0, total: 0 },
      scenarioProgress: {},
      lastLine: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("run() starts a sweep, polls progress, and refreshes scenarios on completion", async () => {
    vi.useFakeTimers();
    mockStartSweep.mockResolvedValue({ status: "running", total: 2 });
    mockGetSweepStatus
      .mockResolvedValueOnce({ status: "running", current: 1, total: 2 })
      .mockResolvedValueOnce({ status: "done", current: 2, total: 2 });

    useSweepRunStore.getState().run({ total: 2 });
    expect(useSweepRunStore.getState().sweeping).toBe(true);

    await vi.advanceTimersByTimeAsync(0); // flush startSweep().then(...)
    await vi.advanceTimersByTimeAsync(1000); // first poll tick -> running
    expect(useSweepRunStore.getState().progress).toEqual({ current: 1, total: 2 });
    expect(useSweepRunStore.getState().sweeping).toBe(true);

    await vi.advanceTimersByTimeAsync(1000); // second poll tick -> done
    expect(useSweepRunStore.getState().sweeping).toBe(false);
    // Just the completion refresh: current:1 on the first-ever tick means
    // scenario 1 is only just starting (nothing finished yet), and the
    // sweep goes straight from there to "done" -- see the dedicated
    // mid-sweep-refresh test below for the actual N -> N+1 transition case.
    expect(mockRefresh).toHaveBeenCalledOnce();
    expect(mockToastSuccess).toHaveBeenCalledOnce();
  });

  it("run() toasts an error and stops polling when the job fails", async () => {
    vi.useFakeTimers();
    mockStartSweep.mockResolvedValue({ status: "running", total: 1 });
    mockGetSweepStatus.mockResolvedValueOnce({ status: "error", message: "boom" });

    useSweepRunStore.getState().run({ total: 1 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(useSweepRunStore.getState().sweeping).toBe(false);
    expect(mockToastError).toHaveBeenCalledWith(expect.stringContaining("boom"));
    expect(mockRefresh).not.toHaveBeenCalled();
  });

  it("run() passes noCache and the current scenario overlays through to startSweep", async () => {
    vi.useFakeTimers();
    mockOverlays = { a: { torch_eff: 0.5 } };
    mockStartSweep.mockResolvedValue({ status: "running", total: 1 });
    mockGetSweepStatus.mockResolvedValueOnce({ status: "done", current: 1, total: 1 });

    useSweepRunStore.getState().run({ total: 1, noCache: true });
    expect(mockStartSweep).toHaveBeenCalledWith({
      scenarios: { a: { torch_eff: 0.5 } },
      noCache: true,
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
  });

  it("run() refuses to start a second job while one is already running", () => {
    useSweepRunStore.setState({ sweeping: true, progress: { current: 0, total: 0 } });

    useSweepRunStore.getState().run();

    expect(mockStartSweep).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith("A sweep is already running");
  });

  it("run()'s poll tick populates scenarioProgress and lastLine from the status payload", async () => {
    vi.useFakeTimers();
    mockStartSweep.mockResolvedValue({ status: "running", total: 1 });
    mockGetSweepStatus
      .mockResolvedValueOnce({
        status: "running",
        current: 1,
        total: 2,
        scenario_progress: { cold_feed: { stage: 1, stage_total: 3 } },
        last_line: "Staged solve: stage 'default' (1/3, 3 reactors)",
      })
      .mockResolvedValueOnce({ status: "done", current: 2, total: 2 });

    useSweepRunStore.getState().run({ total: 2 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(useSweepRunStore.getState().scenarioProgress).toEqual({
      cold_feed: { stage: 1, stageTotal: 3 },
    });
    expect(useSweepRunStore.getState().lastLine).toBe(
      "Staged solve: stage 'default' (1/3, 3 reactors)",
    );

    await vi.advanceTimersByTimeAsync(1000);
    // Cleared once the sweep finishes.
    expect(useSweepRunStore.getState().scenarioProgress).toEqual({});
    expect(useSweepRunStore.getState().lastLine).toBeNull();
  });

  it("refreshes the Scenario Pane as soon as each scenario finishes, not only at the end", async () => {
    vi.useFakeTimers();
    mockStartSweep.mockResolvedValue({ status: "running", total: 3 });
    mockGetSweepStatus
      // Scenario 1 in flight -- nothing finished yet, no refresh due.
      .mockResolvedValueOnce({ status: "running", current: 1, total: 3 })
      // Still scenario 1 (same `current`) -- must not refresh again for it.
      .mockResolvedValueOnce({ status: "running", current: 1, total: 3 })
      // Scenario 1 just finished, scenario 2 starting -- one refresh due.
      .mockResolvedValueOnce({ status: "running", current: 2, total: 3 })
      .mockResolvedValueOnce({ status: "done", current: 3, total: 3 });

    useSweepRunStore.getState().run({ total: 3 });
    await vi.advanceTimersByTimeAsync(0);

    await vi.advanceTimersByTimeAsync(1000);
    expect(mockRefresh).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1000); // repeat of current=1 -- no new refresh
    expect(mockRefresh).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1000); // current 1 -> 2
    expect(mockRefresh).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1000); // done: current 2 -> 3
    expect(mockRefresh).toHaveBeenCalledTimes(2);
  });

  it("hydrate() attaches to an already-running sweep and polls it to completion", async () => {
    vi.useFakeTimers();
    mockGetSweepStatus
      .mockResolvedValueOnce({
        status: "running",
        current: 1,
        total: 2,
        scenario_progress: { a: { stage: null, stage_total: null } },
      })
      .mockResolvedValueOnce({ status: "done", current: 2, total: 2 });

    useSweepRunStore.getState().hydrate();
    await vi.advanceTimersByTimeAsync(0); // flush the initial getSweepStatus()

    expect(useSweepRunStore.getState().sweeping).toBe(true);
    expect(useSweepRunStore.getState().scenarioProgress).toEqual({
      a: { stage: null, stageTotal: null },
    });
    expect(mockStartSweep).not.toHaveBeenCalled(); // attaches, never re-POSTs

    await vi.advanceTimersByTimeAsync(1000); // poll tick -> done
    expect(useSweepRunStore.getState().sweeping).toBe(false);
    // Just the completion refresh: the initial hydrate() snapshot (current:
    // 1) is the first observation this session has made, so it can't tell
    // whether anything finished before it started watching -- current only
    // advances to 2 (scenario 1 done) on the very next, final tick, which
    // goes straight to "done" and refreshes unconditionally there anyway.
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  it("hydrate() is a no-op when nothing is running", async () => {
    mockGetSweepStatus.mockResolvedValue({ status: "idle" });

    useSweepRunStore.getState().hydrate();
    await Promise.resolve();
    await Promise.resolve();

    expect(useSweepRunStore.getState().sweeping).toBe(false);
    expect(mockToastSuccess).not.toHaveBeenCalled();
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("hydrate() is a no-op when this session is already polling its own run()", async () => {
    useSweepRunStore.setState({ sweeping: true, progress: { current: 0, total: 0 } });

    useSweepRunStore.getState().hydrate();

    expect(mockGetSweepStatus).not.toHaveBeenCalled();
  });

  it("run()'s completion auto-selects the first scenario when nothing was active", async () => {
    vi.useFakeTimers();
    mockActiveId = null;
    mockScenarios = [{ id: "BASELINE" }, { id: "C600_P300" }];
    mockStartSweep.mockResolvedValue({ status: "running", total: 2 });
    mockGetSweepStatus.mockResolvedValueOnce({ status: "done", current: 2, total: 2 });

    useSweepRunStore.getState().run({ total: 2 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(mockSetActive).toHaveBeenCalledWith("BASELINE");
  });

  it("run()'s completion re-fetches the existing active scenario instead of switching", async () => {
    vi.useFakeTimers();
    mockActiveId = "C600_P300";
    mockScenarios = [{ id: "BASELINE" }, { id: "C600_P300" }];
    mockStartSweep.mockResolvedValue({ status: "running", total: 2 });
    mockGetSweepStatus.mockResolvedValueOnce({ status: "done", current: 2, total: 2 });

    useSweepRunStore.getState().run({ total: 2 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(mockSetActive).toHaveBeenCalledWith("C600_P300");
    expect(mockSetActive).toHaveBeenCalledOnce();
  });

  it("run()'s completion does nothing when there is no active scenario and none finished", async () => {
    vi.useFakeTimers();
    mockActiveId = null;
    mockScenarios = [];
    mockStartSweep.mockResolvedValue({ status: "running", total: 1 });
    mockGetSweepStatus.mockResolvedValueOnce({ status: "done", current: 1, total: 1 });

    useSweepRunStore.getState().run({ total: 1 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(mockSetActive).not.toHaveBeenCalled();
  });

  describe("stop()", () => {
    it("is a no-op when nothing is sweeping", () => {
      useSweepRunStore.getState().stop();

      expect(mockStopSweep).not.toHaveBeenCalled();
      expect(useSweepRunStore.getState().stopping).toBe(false);
    });

    it("optimistically sets stopping, then the next poll tick confirms it", async () => {
      vi.useFakeTimers();
      mockStartSweep.mockResolvedValue({ status: "running", total: 2 });
      mockStopSweep.mockResolvedValue({ stopping: true });
      mockGetSweepStatus
        .mockResolvedValueOnce({ status: "stopping", current: 1, total: 2 })
        .mockResolvedValueOnce({ status: "cancelled" });

      useSweepRunStore.getState().run({ total: 2 });
      await vi.advanceTimersByTimeAsync(0);

      useSweepRunStore.getState().stop();
      expect(mockStopSweep).toHaveBeenCalledOnce();
      expect(useSweepRunStore.getState().stopping).toBe(true);
      expect(useSweepRunStore.getState().sweeping).toBe(true); // still "in progress" for the UI

      await vi.advanceTimersByTimeAsync(1000); // poll tick -> status "stopping"
      expect(useSweepRunStore.getState().sweeping).toBe(true);
      expect(useSweepRunStore.getState().stopping).toBe(true);

      await vi.advanceTimersByTimeAsync(1000); // poll tick -> status "cancelled"
      expect(useSweepRunStore.getState().sweeping).toBe(false);
      expect(useSweepRunStore.getState().stopping).toBe(false);
    });

    it("a cancelled sweep toasts info, not error, and still refreshes the Scenario Pane", async () => {
      vi.useFakeTimers();
      mockStartSweep.mockResolvedValue({ status: "running", total: 2 });
      mockGetSweepStatus.mockResolvedValueOnce({ status: "cancelled" });

      useSweepRunStore.getState().run({ total: 2 });
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(1000);

      expect(useSweepRunStore.getState().sweeping).toBe(false);
      expect(mockToastInfo).toHaveBeenCalledOnce();
      expect(mockToastError).not.toHaveBeenCalled();
      expect(mockRefresh).toHaveBeenCalledOnce();
    });

    it("reverts the optimistic stopping flag if the stop request itself fails", async () => {
      vi.useFakeTimers();
      mockStartSweep.mockResolvedValue({ status: "running", total: 1 });
      mockStopSweep.mockRejectedValue(new Error("network error"));

      useSweepRunStore.getState().run({ total: 1 });
      await vi.advanceTimersByTimeAsync(0);

      useSweepRunStore.getState().stop();
      expect(useSweepRunStore.getState().stopping).toBe(true);

      await vi.advanceTimersByTimeAsync(0); // flush the rejected stopSweep() promise
      expect(useSweepRunStore.getState().stopping).toBe(false);
      expect(mockToastError).toHaveBeenCalledWith(expect.stringContaining("network error"));
    });
  });
});
