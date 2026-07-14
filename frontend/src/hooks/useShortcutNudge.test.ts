/**
 * Asserts useShortcutNudge: stays silent for the first couple of clicks,
 * nudges once a threshold is reached within the window, resets afterward
 * (so it takes a fresh run of clicks to nudge again), tracks each actionId
 * independently, and forgets clicks that fall outside the window.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useShortcutNudge, NUDGE_THRESHOLD, NUDGE_WINDOW_MS } from "./useShortcutNudge";

const mockToastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: { info: (...args: unknown[]) => mockToastInfo(...args) },
}));

describe("useShortcutNudge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not nudge before the threshold is reached", () => {
    const { result } = renderHook(() => useShortcutNudge());
    for (let i = 0; i < NUDGE_THRESHOLD - 1; i++) {
      result.current("run-simulation", "Ctrl+Enter");
    }
    expect(mockToastInfo).not.toHaveBeenCalled();
  });

  it("nudges with the shortcut label once the threshold is reached within the window", () => {
    const { result } = renderHook(() => useShortcutNudge());
    for (let i = 0; i < NUDGE_THRESHOLD; i++) {
      result.current("run-simulation", "Ctrl+Enter");
    }
    expect(mockToastInfo).toHaveBeenCalledOnce();
    expect(mockToastInfo).toHaveBeenCalledWith(expect.stringContaining("Ctrl+Enter"));
  });

  it("resets after nudging, requiring a fresh run of clicks before nudging again", () => {
    const { result } = renderHook(() => useShortcutNudge());
    for (let i = 0; i < NUDGE_THRESHOLD; i++) {
      result.current("run-simulation", "Ctrl+Enter");
    }
    expect(mockToastInfo).toHaveBeenCalledOnce();

    result.current("run-simulation", "Ctrl+Enter");
    result.current("run-simulation", "Ctrl+Enter");
    expect(mockToastInfo).toHaveBeenCalledOnce();

    result.current("run-simulation", "Ctrl+Enter");
    expect(mockToastInfo).toHaveBeenCalledTimes(2);
  });

  it("tracks each actionId independently", () => {
    const { result } = renderHook(() => useShortcutNudge());
    for (let i = 0; i < NUDGE_THRESHOLD - 1; i++) {
      result.current("run-simulation", "Ctrl+Enter");
    }
    result.current("toggle-left-sidebar", "Ctrl+B");
    expect(mockToastInfo).not.toHaveBeenCalled();

    result.current("run-simulation", "Ctrl+Enter");
    expect(mockToastInfo).toHaveBeenCalledOnce();
    expect(mockToastInfo).toHaveBeenCalledWith(expect.stringContaining("Ctrl+Enter"));
  });

  it("forgets clicks once they fall outside the nudge window", () => {
    const { result } = renderHook(() => useShortcutNudge());
    result.current("run-simulation", "Ctrl+Enter");
    result.current("run-simulation", "Ctrl+Enter");

    vi.setSystemTime(NUDGE_WINDOW_MS + 1);
    result.current("run-simulation", "Ctrl+Enter");

    expect(mockToastInfo).not.toHaveBeenCalled();
  });
});
