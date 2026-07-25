/**
 * Asserts the shared sweep-run store: starts a job, polls to completion,
 * refreshes scenarios and toasts on success/failure, passes `noCache`
 * through, and refuses a second job while one is already running. RunControl's
 * "Run Sweep" calls this single store instead of owning its own poll loop.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockStartSweep = vi.fn();
const mockGetSweepStatus = vi.fn();
vi.mock("@/api/sweep", () => ({
  startSweep: (...args: unknown[]) => mockStartSweep(...args),
  getSweepStatus: (...args: unknown[]) => mockGetSweepStatus(...args),
}));

const mockRefresh = vi.fn();
const mockSetActive = vi.fn();
let mockActiveId: string | null = null;
let mockScenarios: Array<{ id: string }> = [];
vi.mock("./scenarioStore", () => ({
  useScenarioStore: {
    getState: () => ({
      refresh: mockRefresh,
      setActive: mockSetActive,
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
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

import { useSweepRunStore } from "./sweepStore";

describe("sweepStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockActiveId = null;
    mockScenarios = [];
    useSweepRunStore.setState({
      sweeping: false,
      progress: { current: 0, total: 0 },
      scenarioProgress: {},
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

  it("run() passes noCache through to startSweep, forcing a full recompute", async () => {
    vi.useFakeTimers();
    mockStartSweep.mockResolvedValue({ status: "running", total: 1 });
    mockGetSweepStatus.mockResolvedValueOnce({ status: "done", current: 1, total: 1 });

    useSweepRunStore.getState().run({ total: 1, noCache: true });
    expect(mockStartSweep).toHaveBeenCalledWith({ noCache: true });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
  });

  it("run() refuses to start a second job while one is already running", () => {
    useSweepRunStore.setState({ sweeping: true, progress: { current: 0, total: 0 } });

    useSweepRunStore.getState().run();

    expect(mockStartSweep).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith("A sweep is already running");
  });

  it("run()'s poll tick populates scenarioProgress from the status payload", async () => {
    vi.useFakeTimers();
    mockStartSweep.mockResolvedValue({ status: "running", total: 1 });
    mockGetSweepStatus
      .mockResolvedValueOnce({
        status: "running",
        current: 1,
        total: 2,
        scenario_progress: { cold_feed: { stage: 1, stage_total: 3 } },
      })
      .mockResolvedValueOnce({ status: "done", current: 2, total: 2 });

    useSweepRunStore.getState().run({ total: 2 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(useSweepRunStore.getState().scenarioProgress).toEqual({
      cold_feed: { stage: 1, stageTotal: 3 },
    });

    await vi.advanceTimersByTimeAsync(1000);
    // Cleared once the sweep finishes.
    expect(useSweepRunStore.getState().scenarioProgress).toEqual({});
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
    expect(mockRefresh).toHaveBeenCalledOnce();
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
});
