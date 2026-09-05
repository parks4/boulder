/**
 * Asserts useSimulationSSE's terminal handling:
 * - the "stopped" SSE event clears isRunning (via the store's `stopped()`
 *   action) instead of leaving the run stuck forever.
 * - the server's own `event: error` surfaces its message.
 * - a native connection error is NOT mistaken for a server error, and:
 *   - while the browser is still reconnecting (readyState CONNECTING) the
 *     stream is left alone -- a proxy dropping a long-lived stream used to
 *     be reported as "Connection to simulation lost" while the server log
 *     held the run's real failure;
 *   - once it is dead (CLOSED, or repeated failures) the run's real
 *     error_message is fetched from the server before falling back to the
 *     generic message -- and isRunning never stays stuck true.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useSimulationSSE } from "./useSimulationSSE";
import { fetchSimulationResults } from "@/api/simulations";

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  listeners: Record<string, Array<(e: { data?: string }) => void>> = {};
  readyState = FakeEventSource.OPEN;
  closed = false;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: (e: { data?: string }) => void): void {
    (this.listeners[type] ??= []).push(cb);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  /** A server-sent event (a MessageEvent carrying JSON). */
  emit(type: string, data: unknown): void {
    for (const cb of this.listeners[type] ?? []) cb({ data: JSON.stringify(data) });
  }

  /** The browser's native connection error: same "error" name, no data. */
  emitNativeError(readyState: number): void {
    this.readyState = readyState;
    for (const cb of this.listeners.error ?? []) cb({});
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

vi.mock("@/api/simulations", () => ({
  fetchSimulationResults: vi.fn(),
}));
const mockFetchResults = vi.mocked(fetchSimulationResults);

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

  it("surfaces the server's own 'error' event message", () => {
    renderHook(() => useSimulationSSE());
    const source = FakeEventSource.instances[0];

    source.emit("error", { message: "Cantera advance failed at t=0.1s" });

    expect(mockSetError).toHaveBeenCalledWith("Cantera advance failed at t=0.1s");
    expect(mockFetchResults).not.toHaveBeenCalled();
    expect(source.closed).toBe(true);
  });

  it("leaves a reconnecting stream alone instead of reporting a lost connection", () => {
    renderHook(() => useSimulationSSE());
    const source = FakeEventSource.instances[0];

    source.emitNativeError(FakeEventSource.CONNECTING);

    expect(mockSetError).not.toHaveBeenCalled();
    expect(mockFetchResults).not.toHaveBeenCalled();
    expect(source.closed).toBe(false);
  });

  it("gives up after repeated failed reconnects so isRunning cannot stay stuck", async () => {
    mockFetchResults.mockRejectedValue(new Error("API 404: not found"));
    renderHook(() => useSimulationSSE());
    const source = FakeEventSource.instances[0];

    source.emitNativeError(FakeEventSource.CONNECTING);
    source.emitNativeError(FakeEventSource.CONNECTING);
    expect(source.closed).toBe(false);
    source.emitNativeError(FakeEventSource.CONNECTING);

    expect(source.closed).toBe(true);
    await vi.waitFor(() =>
      expect(mockSetError).toHaveBeenCalledWith("Connection to simulation lost"),
    );
  });

  it("reports the run's real error_message when the stream dies on a failed run", async () => {
    mockFetchResults.mockResolvedValue({
      status: "error",
      is_complete: false,
      error_message: "Mechanism file not found: foo.yaml",
    } as never);
    renderHook(() => useSimulationSSE());
    const source = FakeEventSource.instances[0];

    source.emitNativeError(FakeEventSource.CLOSED);

    expect(source.closed).toBe(true);
    expect(mockFetchResults).toHaveBeenCalledWith("sim-123");
    await vi.waitFor(() =>
      expect(mockSetError).toHaveBeenCalledWith("Mechanism file not found: foo.yaml"),
    );
  });

  it("falls back to 'Connection to simulation lost' when the server has no error for the run", async () => {
    mockFetchResults.mockResolvedValue({ status: "running", is_complete: false } as never);
    renderHook(() => useSimulationSSE());
    const source = FakeEventSource.instances[0];

    source.emitNativeError(FakeEventSource.CLOSED);

    await vi.waitFor(() =>
      expect(mockSetError).toHaveBeenCalledWith("Connection to simulation lost"),
    );
  });
});
