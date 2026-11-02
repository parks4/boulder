/**
 * Vitest tests for the host status chip in the top bar.
 *
 * Asserts:
 * - the chip renders the host's text, tone and tooltip, and links to `href`;
 * - the request carries the selected scenario id, and the fingerprint when held;
 * - it re-fetches when the selected scenario changes and after a solve
 *   (single run, and a sweep ending), but not while a run is in flight;
 * - a network error, an HTTP error or an invalid response renders a neutral
 *   "status unavailable" chip with the reason as tooltip;
 * - an unsafe `href` is never rendered as a link.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { HeaderStatus } from "./HeaderStatus";
import { parseHostStatus, safeHref } from "@/lib/hostStatus";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSweepRunStore } from "@/stores/sweepStore";

const fetchMock = vi.fn();

function answer(body: unknown, ok = true) {
  fetchMock.mockResolvedValue({ ok, status: ok ? 200 : 503, json: async () => body });
}

function lastUrl(): URL {
  const calls = fetchMock.mock.calls;
  return new URL(String(calls[calls.length - 1][0]), "http://x");
}

describe("HeaderStatus", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    useScenarioStore.setState({ activeId: null });
    useSimulationStore.getState().clearResults();
    useSweepRunStore.setState({ sweeping: false });
    answer({ text: "recorded", tone: "ok", href: "/runs/1", tooltip: "in the index" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the response as a link chip", async () => {
    render(<HeaderStatus statusUrl="/api/host/status" />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("recorded");
    expect(chip).toHaveAttribute("data-tone", "ok");
    expect(chip).toHaveAttribute("href", "/runs/1");
    expect(chip).toHaveAttribute("title", "in the index");
    expect(lastUrl().pathname).toBe("/api/host/status");
    expect(lastUrl().searchParams.get("scenario")).toBe("BASELINE");
    expect(lastUrl().searchParams.has("fingerprint")).toBe(false);
  });

  it("renders a plain chip without href", async () => {
    answer({ text: "not recorded", tone: "warn" });
    render(<HeaderStatus statusUrl="/s" />);
    const chip = await screen.findByTestId("header-status");
    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveAttribute("data-tone", "warn");
  });

  it("re-fetches on scenario change, with the scenario id", async () => {
    render(<HeaderStatus statusUrl="/s" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => useScenarioStore.setState({ activeId: "case 2/a" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(lastUrl().searchParams.get("scenario")).toBe("case 2/a");
  });

  it("re-fetches after a solve, sending the fingerprint when the GUI holds one", async () => {
    render(<HeaderStatus statusUrl="/s" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => useSimulationStore.getState().beginSimulationRun());
    expect(fetchMock).toHaveBeenCalledTimes(1); // nothing asked mid-run
    act(() => useSimulationStore.getState().setResults({} as never, "abc123"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(lastUrl().searchParams.get("fingerprint")).toBe("abc123");
  });

  it("re-fetches when a sweep ends, not while it runs", async () => {
    render(<HeaderStatus statusUrl="/s" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => useSweepRunStore.setState({ sweeping: true }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    act(() => useSweepRunStore.setState({ sweeping: false }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it.each([
    ["an invalid tone", { text: "x", tone: "purple" }, "invalid tone"],
    ["a missing text", { tone: "ok" }, "missing text"],
    ["a non-object", "oops", "not an object"],
  ])("shows 'status unavailable' for %s", async (_name, body, reason) => {
    answer(body);
    render(<HeaderStatus statusUrl="/s" />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("status unavailable");
    expect(chip).toHaveAttribute("data-tone", "neutral");
    expect(chip.getAttribute("title")).toContain(reason);
  });

  it("shows 'status unavailable' on a network error", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    render(<HeaderStatus statusUrl="/s" />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("status unavailable");
    expect(chip).toHaveAttribute("title", "offline");
  });

  it("shows 'status unavailable' on an HTTP error", async () => {
    answer({}, false);
    render(<HeaderStatus statusUrl="/s" />);
    expect(await screen.findByTestId("header-status")).toHaveAttribute("title", "HTTP 503");
  });

  it("never renders an unsafe href as a link", async () => {
    answer({ text: "x", tone: "ok", href: "javascript:alert(1)" });
    render(<HeaderStatus statusUrl="/s" />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("status unavailable");
    expect(chip).not.toHaveAttribute("href");
  });
});

describe("safeHref", () => {
  it.each([
    ["/runs/1", "/runs/1"],
    ["https://example.com/a", "https://example.com/a"],
    ["javascript:alert(1)", null],
    ["//evil.example", null],
    ["runs", null],
    ["/a b", null],
    ["/a\\b", null],
    ["data:text/html,x", null],
    [42, null],
  ])("%j -> %j", (href, expected) => {
    expect(safeHref(href)).toBe(expected);
  });

  it("parseHostStatus drops nothing it accepts", () => {
    expect(parseHostStatus({ text: "t", tone: "error", tooltip: "w", href: "/p" })).toEqual({
      text: "t",
      tone: "error",
      tooltip: "w",
      href: "/p",
    });
  });
});
