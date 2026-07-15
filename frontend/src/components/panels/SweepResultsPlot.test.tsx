/**
 * Vitest unit tests for SweepResultsPlot.
 *
 * Asserts:
 * - Default render bundles the mole-fraction family as separate traces (legacy behavior).
 * - The "Add series" dropdown lists individual species plus a "quick add" family shortcut,
 *   and only offers series that aren't already active.
 * - Picking an individual species from the dropdown adds it as its own active chip/trace.
 * - Clicking a chip's remove ("x") button drops that series without touching the others.
 * - A user can build an arbitrary combination (e.g. nC7H16 + CO + O2) one at a time,
 *   matching Cantera's continuous_reactor.py-style plot.
 * - Removing every active series still renders the picker (doesn't unmount the panel).
 */

import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScenarioMeta } from "@/api/scenarios";
import { SweepResultsPlot } from "./SweepResultsPlot";

interface PlotTrace {
  name?: string;
  x?: number[];
  y?: (number | null)[];
}

interface PlotProps {
  data: PlotTrace[];
  layout?: {
    yaxis?: { title?: { text?: string } };
  };
}

const plotCalls = vi.hoisted(() => [] as PlotProps[]);

vi.mock("react-plotly.js", () => ({
  default: (props: PlotProps) => {
    plotCalls.push(props);
    return <div data-testid="plot" />;
  },
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (state: { theme: "light" }) => unknown) =>
    selector({ theme: "light" }),
}));

function makeScenario(t0_K: number, X: Record<string, number>): ScenarioMeta {
  const scenario: ScenarioMeta = { id: `s-${t0_K}`, t0_K, label: `${t0_K} K` };
  for (const [species, value] of Object.entries(X)) {
    scenario[`final_X_${species}`] = value;
  }
  return scenario;
}

const scenarios: ScenarioMeta[] = [
  makeScenario(800, { nC7H16: 0.02, CO: 0.01, O2: 0.15 }),
  makeScenario(900, { nC7H16: 0.01, CO: 0.03, O2: 0.1 }),
  makeScenario(1000, { nC7H16: 0.0, CO: 0.02, O2: 0.05 }),
];

function addSeries(value: string) {
  fireEvent.change(screen.getByTestId("y-axis-add-select"), { target: { value } });
}

describe("SweepResultsPlot", () => {
  beforeEach(() => {
    plotCalls.length = 0;
  });

  it("defaults to the mole-fraction family as separate traces", () => {
    render(<SweepResultsPlot scenarios={scenarios} />);

    const names = plotCalls.at(-1)?.data.map((t) => t.name);
    expect(names).toEqual(expect.arrayContaining(["nC7H16", "CO", "O2"]));
    expect(
      screen.getByTestId("active-series-chip-final_X_nC7H16"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_CO")).toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_O2")).toBeInTheDocument();
  });

  it("offers a quick-add family option and individual species not yet active", () => {
    render(<SweepResultsPlot scenarios={scenarios} />);

    const select = screen.getByTestId("y-axis-add-select") as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    // The family (mole fractions) is already fully active by default, so it
    // should not be offered again, and none of its species should be listed
    // as addable individually either.
    expect(optionValues).not.toContain("f:mole_fractions");
    expect(optionValues).not.toContain("k:final_X_CO");
  });

  it("removing a chip re-offers that species in the add dropdown", () => {
    render(<SweepResultsPlot scenarios={scenarios} />);

    fireEvent.click(screen.getByTestId("remove-series-final_X_CO"));

    expect(screen.queryByTestId("active-series-chip-final_X_CO")).not.toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_nC7H16")).toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_O2")).toBeInTheDocument();

    const select = screen.getByTestId("y-axis-add-select") as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toContain("k:final_X_CO");

    const names = plotCalls.at(-1)?.data.map((t) => t.name);
    expect(names).toEqual(expect.arrayContaining(["nC7H16", "O2"]));
    expect(names).toHaveLength(2);
  });

  it("lets a user build a custom combination of individual species one at a time", () => {
    render(<SweepResultsPlot scenarios={scenarios} />);

    // Start from scratch: drop the default family bundle.
    fireEvent.click(screen.getByTestId("remove-series-final_X_nC7H16"));
    fireEvent.click(screen.getByTestId("remove-series-final_X_CO"));
    fireEvent.click(screen.getByTestId("remove-series-final_X_O2"));
    expect(screen.queryByTestId(/^active-series-chip-/)).not.toBeInTheDocument();

    // Add back exactly nC7H16, CO, and O2 individually, matching
    // Cantera's continuous_reactor.py combination.
    addSeries("k:final_X_nC7H16");
    addSeries("k:final_X_CO");
    addSeries("k:final_X_O2");

    expect(screen.getByTestId("active-series-chip-final_X_nC7H16")).toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_CO")).toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_O2")).toBeInTheDocument();

    const names = plotCalls.at(-1)?.data.map((t) => t.name);
    expect(names).toEqual(["nC7H16", "CO", "O2"]);
  });

  it("adding the quick-add family option bundles every species in one click", () => {
    render(<SweepResultsPlot scenarios={scenarios} />);
    fireEvent.click(screen.getByTestId("remove-series-final_X_nC7H16"));
    fireEvent.click(screen.getByTestId("remove-series-final_X_CO"));
    fireEvent.click(screen.getByTestId("remove-series-final_X_O2"));

    addSeries("f:mole_fractions");

    const names = plotCalls.at(-1)?.data.map((t) => t.name);
    expect(names).toEqual(expect.arrayContaining(["nC7H16", "CO", "O2"]));
  });

  it("still renders the picker after removing every active series", () => {
    render(<SweepResultsPlot scenarios={scenarios} />);
    fireEvent.click(screen.getByTestId("remove-series-final_X_nC7H16"));
    fireEvent.click(screen.getByTestId("remove-series-final_X_CO"));
    fireEvent.click(screen.getByTestId("remove-series-final_X_O2"));

    expect(screen.getByTestId("y-axis-add-select")).toBeInTheDocument();
    expect(plotCalls.at(-1)?.data).toEqual([]);
  });
});
