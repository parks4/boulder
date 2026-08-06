/**
 * Asserts useSimulationSSE's stop-related terminal handling:
 * - the "stopped" SSE event clears isRunning (via the store's `stopped()`
 *   action) instead of leaving the run stuck forever.
 * - a dropped connection (native EventSource `onerror`) now surfaces as a
 *   run error instead of silently closing the stream with isRunning still
 *   true and no feedback -- the bug that motivated this fix.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useSimulationSSE } from "./useSimulationSSE";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, Array<(e: { data: string }) => void>> = {};
  onerror: (() => void) | null = null;
  closed = false;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: (e: { data: string }) => void): void {
    (this.listeners[type] ??= []).push(cb);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data: unknown): void {
    for (const cb of this.listeners[type] ?? []) cb({ data: JSON.stringify(data) });
  }
}

const mockUpdateProgress = vi.fn();
const mockSetResults = vi.fn();
const mockSetError = vi.fn();
const mockStopped = vi.fn();

let mockSimulationId: string | null = "sim-123";
const mockIsRunning = true;

vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: () => ({
    simulationId: mockSimulationId,
    isRunning: mockIsRunning,
    updateProgress: mockUpdateProgress,
    setResults: mockSetResults,
    setError: mockSetError,
    stopped: mockStopped,
  }),
}));

describe("useSimulationSSE", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.instances = [];
    mockSimulationId = "sim-123";
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("clears isRunning via stopped() on the SSE 'stopped' event, without an error", () => {
    renderHook(() => useSimulationSSE());
    const source = FakeEventSource.instances[0];

    source.emit("stopped", { is_running: false, is_stopping: true });

    expect(mockStopped).toHaveBeenCalledOnce();
    expect(mockSetError).not.toHaveBeenCalled();
    expect(source.closed).toBe(true);
  });

  it("surfaces a dropped connection as a run error instead of leaving isRunning stuck", () => {
    renderHook(() => useSimulationSSE());
    const source = FakeEventSource.instances[0];

    source.onerror?.();

    expect(mockSetError).toHaveBeenCalledWith(expect.stringContaining("Connection"));
    expect(source.closed).toBe(true);
  });
});
