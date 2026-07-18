/**
 * Asserts the shared sweep-run store: starts a job, polls to completion,
 * refreshes scenarios and toasts on success/failure, passes `noCache`
 * through, and refuses a second job while one is already running. Both
 * RunControl's "Run Sweep" and the Scenario Pane's "Regenerate cache" call
 * this single store instead of each owning their own poll loop.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockStartSweep = vi.fn();
const mockGetSweepStatus = vi.fn();
vi.mock("@/api/sweep", () => ({
  startSweep: (...args: unknown[]) => mockStartSweep(...args),
  getSweepStatus: (...args: unknown[]) => mockGetSweepStatus(...args),
}));

const mockRefresh = vi.fn();
vi.mock("./scenarioStore", () => ({
  useScenarioStore: { getState: () => ({ refresh: mockRefresh }) },
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
    useSweepRunStore.setState({ sweeping: false, progress: { current: 0, total: 0 } });
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

  it("run() passes noCache through to startSweep (the Regenerate cache action)", async () => {
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
});
