/**
 * Vitest tests for the host status chip in the top bar.
 *
 * Asserts:
 * - the chip renders the host's text, tone and tooltip, and links to `href`;
 * - the request is `/api/ui/header-status` with only the scenario id (none for the base);
 * - it re-fetches when the selected scenario changes, when a result lands, when a
 *   sweep ends and when `config.metadata` changes, but not while a run is in flight;
 * - a null status renders nothing, and a 500's `detail` is the chip's tooltip;
 * - a network error, an HTTP error or an invalid response renders a neutral
 *   "status unavailable" chip with the reason as tooltip;
 * - an unsafe `href` is never rendered as a link;
 * - a late response for a superseded request is dropped.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { HeaderStatus } from "./HeaderStatus";
import { parseHostStatus, safeHref } from "@/lib/hostStatus";
import { useConfigStore } from "@/stores/configStore";
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
    answer({
      status: { text: "recorded", tone: "ok", href: "/runs/1", tooltip: "in the index" },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the response as a link chip", async () => {
    render(<HeaderStatus />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("recorded");
    expect(chip).toHaveAttribute("data-tone", "ok");
    expect(chip).toHaveAttribute("href", "/runs/1");
    expect(chip).toHaveAttribute("title", "in the index");
    expect(lastUrl().pathname).toBe("/api/ui/header-status");
    expect(lastUrl().search).toBe("");
  });

  it("renders a plain chip without href", async () => {
    answer({ status: { text: "not recorded", tone: "warn" } });
    render(<HeaderStatus />);
    const chip = await screen.findByTestId("header-status");
    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveAttribute("data-tone", "warn");
  });

  it("renders nothing for a null status", async () => {
    answer({ status: null });
    render(<HeaderStatus />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("header-status")).toBeNull();
  });

  it("re-fetches on scenario change, with the scenario id", async () => {
    render(<HeaderStatus />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => useScenarioStore.setState({ activeId: "case 2/a" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(lastUrl().searchParams.get("scenario_id")).toBe("case 2/a");
  });

  it("re-fetches when a result lands, not while a run is in flight", async () => {
    render(<HeaderStatus />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => useSimulationStore.getState().beginSimulationRun());
    expect(fetchMock).toHaveBeenCalledTimes(1); // nothing asked mid-run
    act(() => useSimulationStore.getState().setResults({} as never));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("re-fetches when a sweep ends, not while it runs", async () => {
    render(<HeaderStatus />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => useSweepRunStore.setState({ sweeping: true }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    act(() => useSweepRunStore.setState({ sweeping: false }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("re-fetches when config.metadata changes", async () => {
    render(<HeaderStatus />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => {
      const { config } = useConfigStore.getState();
      useConfigStore.setState({ config: { ...config, metadata: { title: "x" } } });
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("drops a late response for a superseded request", async () => {
    let releaseFirst: (v: unknown) => void = () => {};
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        releaseFirst = resolve;
      }),
    );
    render(<HeaderStatus />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    answer({ status: { text: "second", tone: "ok" } });
    act(() => useScenarioStore.setState({ activeId: "other" }));
    expect(await screen.findByText("second")).toBeInTheDocument();
    await act(async () => {
      releaseFirst({ ok: true, status: 200, json: async () => ({ status: { text: "first", tone: "ok" } }) });
    });
    expect(screen.queryByText("first")).toBeNull();
    expect(screen.getByText("second")).toBeInTheDocument();
  });

  it.each([
    ["an invalid tone", { status: { text: "x", tone: "purple" } }, "invalid tone"],
    ["a missing text", { status: { tone: "ok" } }, "missing text"],
    ["a non-object", "oops", "not an object"],
  ])("shows 'status unavailable' for %s", async (_name, body, reason) => {
    answer(body);
    render(<HeaderStatus />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("status unavailable");
    expect(chip).toHaveAttribute("data-tone", "neutral");
    expect(chip.getAttribute("title")).toContain(reason);
  });

  it("shows 'status unavailable' on a network error", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    render(<HeaderStatus />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("status unavailable");
    expect(chip).toHaveAttribute("title", "offline");
  });

  it("shows 'status unavailable' on an HTTP error", async () => {
    answer({}, false);
    render(<HeaderStatus />);
    expect(await screen.findByTestId("header-status")).toHaveAttribute("title", "HTTP 503");
  });

  it("shows the server's 500 detail as the tooltip", async () => {
    answer({ detail: "index down" }, false);
    render(<HeaderStatus />);
    const chip = await screen.findByTestId("header-status");
    expect(chip).toHaveTextContent("status unavailable");
    expect(chip).toHaveAttribute("title", "index down");
  });

  it("never renders an unsafe href as a link", async () => {
    answer({ status: { text: "x", tone: "ok", href: "javascript:alert(1)" } });
    render(<HeaderStatus />);
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

  it("parseHostStatus fills the optional fields", () => {
    expect(
      parseHostStatus({ status: { text: "t", tone: "error", tooltip: "w", href: "/p" } }),
    ).toEqual({ text: "t", tone: "error", tooltip: "w", href: "/p", new_tab: false });
  });
});
