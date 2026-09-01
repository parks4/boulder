/**
 * Vitest unit tests for SweepResultsPlot.
 *
 * Asserts:
 * - Default render bundles the mole-fraction family as separate traces (legacy behavior).
 * - The "Add series" picker lists individual species plus a "quick add" family shortcut,
 *   and only offers series that aren't already active.
 * - Picking an individual species from the picker adds it as its own active chip/trace.
 * - Clicking a chip's remove ("x") button drops that series without touching the others.
 * - A user can build an arbitrary combination (e.g. nC7H16 + CO + O2) one at a time,
 *   matching Cantera's continuous_reactor.py-style plot.
 * - Removing every active series still renders the picker (doesn't unmount the panel).
 * - Typing into either picker fuzzy-filters its option list.
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

/** Opens the "Add series" picker (a type-to-filter combobox, not a native
 * `<select>`) and clicks the option for `value`, e.g. "k:final_X_CO" or
 * "f:mole_fractions". */
function addSeries(value: string) {
  fireEvent.focus(screen.getByTestId("y-axis-add-select"));
  fireEvent.click(screen.getByTestId(`y-axis-add-select-option-${value}`));
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

    fireEvent.focus(screen.getByTestId("y-axis-add-select"));
    // The family (mole fractions) is already fully active by default, so it
    // should not be offered again, and none of its species should be listed
    // as addable individually either.
    expect(
      screen.queryByTestId("y-axis-add-select-option-f:mole_fractions"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("y-axis-add-select-option-k:final_X_CO"),
    ).not.toBeInTheDocument();
  });

  it("removing a chip re-offers that species in the add picker", () => {
    render(<SweepResultsPlot scenarios={scenarios} />);

    fireEvent.click(screen.getByTestId("remove-series-final_X_CO"));

    expect(screen.queryByTestId("active-series-chip-final_X_CO")).not.toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_nC7H16")).toBeInTheDocument();
    expect(screen.getByTestId("active-series-chip-final_X_O2")).toBeInTheDocument();

    fireEvent.focus(screen.getByTestId("y-axis-add-select"));
    expect(
      screen.getByTestId("y-axis-add-select-option-k:final_X_CO"),
    ).toBeInTheDocument();

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

  describe("input/output labeling", () => {
    function makeKpiScenario(
      t0_K: number,
      extra: Record<string, number>,
    ): ScenarioMeta {
      return { id: `s-${t0_K}`, t0_K, label: `${t0_K} K`, ...extra };
    }

    const kpiScenarios: ScenarioMeta[] = [
      makeKpiScenario(800, { efficiency: 75.0, "in.downstream.pressure": 1.05e5 }),
      makeKpiScenario(900, { efficiency: 77.5, "in.downstream.pressure": 1.3e5 }),
    ];

    it("labels an auto-walked node.property key as input with its unit", () => {
      render(<SweepResultsPlot scenarios={kpiScenarios} />);

      // efficiency is active by default (first available series); pressure
      // is still offered in the "add series" picker.
      fireEvent.focus(screen.getByTestId("y-axis-add-select"));
      const pressureOption = screen.getByTestId(
        "y-axis-add-select-option-k:in.downstream.pressure",
      );
      expect(pressureOption).toHaveTextContent("downstream.pressure (Pa, input)");
    });

    it("labels a host KPI attr as output, with its unit when supplied", () => {
      render(<SweepResultsPlot scenarios={kpiScenarios} units={{ efficiency: "%" }} />);

      expect(
        screen.getByTestId("active-series-chip-efficiency"),
      ).toHaveTextContent("Efficiency (%, output)");
    });

    it("omits an empty unit parenthetical when no unit is known", () => {
      render(<SweepResultsPlot scenarios={kpiScenarios} />);

      expect(
        screen.getByTestId("active-series-chip-efficiency"),
      ).toHaveTextContent("Efficiency (output)");
    });
  });

  describe("fuzzy filters", () => {
    it("narrows the X axis picker to keys whose label matches the typed text", () => {
      render(<SweepResultsPlot scenarios={scenarios} />);

      const input = screen.getByTestId("x-axis-select");
      fireEvent.focus(input);
      fireEvent.change(input, { target: { value: "temp" } });

      expect(screen.getByTestId("x-axis-select-option-t0_K")).toBeInTheDocument();
      expect(
        screen.queryByTestId("x-axis-select-option-final_X_CO"),
      ).not.toBeInTheDocument();
    });

    it("narrows the Y axis add-series picker to labels matching the typed text", () => {
      render(<SweepResultsPlot scenarios={scenarios} />);
      // Drop the default mole-fraction family so its species are addable again.
      fireEvent.click(screen.getByTestId("remove-series-final_X_nC7H16"));
      fireEvent.click(screen.getByTestId("remove-series-final_X_CO"));
      fireEvent.click(screen.getByTestId("remove-series-final_X_O2"));

      const input = screen.getByTestId("y-axis-add-select");
      fireEvent.focus(input);
      fireEvent.change(input, { target: { value: "c7" } });

      expect(
        screen.getByTestId("y-axis-add-select-option-k:final_X_nC7H16"),
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId("y-axis-add-select-option-k:final_X_CO"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId("y-axis-add-select-option-f:mole_fractions"),
      ).not.toBeInTheDocument();
    });
  });

  describe("default axis orientation", () => {
    /** No `t0_K`: the swept knob is an input attr, the KPI is an output.
     * `carbon_yield` sorts before `in.downstream.pressure` (`c` < `i`), which
     * is exactly the case the old first-key-alphabetically default got wrong. */
    const kpiVsInput: ScenarioMeta[] = [
      {
        id: "s-1",
        label: "1",
        carbon_yield: 75.1,
        "in.downstream.pressure": 1.05e5,
      },
      {
        id: "s-2",
        label: "2",
        carbon_yield: 77.4,
        "in.downstream.pressure": 1.3e5,
      },
    ];

    it("puts the swept input on X and the KPI on Y, not the reverse", () => {
      render(<SweepResultsPlot scenarios={kpiVsInput} />);

      const xSelect = screen.getByTestId("x-axis-select") as HTMLInputElement;
      expect(xSelect.value).toBe("downstream.pressure (Pa, input)");
      expect(
        screen.getByTestId("active-series-chip-carbon_yield"),
      ).toBeInTheDocument();

      // The plotted X values must be the pressures, ascending.
      expect(plotCalls.at(-1)?.data[0]?.x).toEqual([1.05e5, 1.3e5]);
      expect(plotCalls.at(-1)?.data[0]?.y).toEqual([75.1, 77.4]);
    });

    it("still prefers t0_K for X when present, so existing sweeps are unchanged", () => {
      const withT0: ScenarioMeta[] = kpiVsInput.map((s, i) => ({
        ...s,
        t0_K: 800 + 100 * i,
      }));
      render(<SweepResultsPlot scenarios={withT0} />);

      const xSelect = screen.getByTestId("x-axis-select") as HTMLInputElement;
      expect(xSelect.value).toBe("Temperature (K) (output)");
    });

    it("keeps a KPI on Y even when another input sorts ahead of it", () => {
      const twoInputs: ScenarioMeta[] = [
        {
          id: "s-1",
          label: "1",
          "in.a.pressure": 1e5,
          "in.b.temperature": 300,
          yield_pct: 40,
        },
        {
          id: "s-2",
          label: "2",
          "in.a.pressure": 2e5,
          "in.b.temperature": 400,
          yield_pct: 60,
        },
      ];
      render(<SweepResultsPlot scenarios={twoInputs} />);

      const xSelect = screen.getByTestId("x-axis-select") as HTMLInputElement;
      expect(xSelect.value).toBe("a.pressure (Pa, input)");
      // "in.b.temperature" sorts before "yield_pct", but it is an input:
      // the KPI must still be what gets plotted.
      expect(
        screen.getByTestId("active-series-chip-yield_pct"),
      ).toBeInTheDocument();
    });
  });
});
