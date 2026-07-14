/**
 * Vitest unit tests for PlotsTab.
 *
 * Asserts:
 * - Single-sample steady results are rendered with visible markers.
 */

import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConfigStore } from "@/stores/configStore";
import { useSelectionStore } from "@/stores/selectionStore";
import type { SimulationProgress } from "@/types/simulation";
import { PlotsTab } from "./PlotsTab";

interface PlotTrace {
  mode?: string;
  x?: number[];
  y?: number[];
  name?: string;
  visible?: true | "legendonly";
}

interface PlotProps {
  data: PlotTrace[];
  layout?: {
    yaxis?: Record<string, unknown>;
    title?: { text?: string };
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

const steadySingleSample: SimulationProgress = {
  is_running: false,
  is_complete: true,
  times: [0],
  reactors_series: {
    steady_reactor: {
      T: [1011.31],
      P: [101325],
      X: {
        O2: [0.2],
        N2: [0.7],
      },
      Y: {
        O2: [0.23],
        N2: [0.77],
      },
    },
  },
};

const spatialPressureSample = {
  is_running: false,
  is_complete: true,
  times: [],
  reactors_series: {
    pfr: {
      is_spatial: true,
      x: [5.7, 5.8, 5.9],
      T: [1200, 1210, 1220],
      P: ["100000", "101325", "102500"],
      X: { N2: [0.8, 0.79, 0.78] },
      Y: { N2: [0.8, 0.79, 0.78] },
    },
  },
} as unknown as SimulationProgress;

describe("PlotsTab", () => {
  beforeEach(() => {
    plotCalls.length = 0;
    useSelectionStore.setState({
      selectedElement: { type: "node", data: { id: "steady_reactor" } },
    });
    useConfigStore.getState().resetConfig();
  });

  it("shows markers for single-sample steady-state traces", () => {
    render(<PlotsTab data={steadySingleSample} />);

    expect(plotCalls[0].data[0]).toMatchObject({
      x: [0],
      y: [738.16],
      mode: "lines+markers",
    });
    expect(plotCalls[1].data[0]).toMatchObject({
      x: [0],
      y: [101325],
      mode: "lines+markers",
    });
    expect(plotCalls[1].layout?.yaxis).toMatchObject({
      rangemode: "tozero",
      tickformat: ",.0f",
    });
  });

  it("uses a zero baseline for spatial pressure profiles", () => {
    useSelectionStore.setState({
      selectedElement: { type: "node", data: { id: "pfr" } },
    });
    render(<PlotsTab data={spatialPressureSample} />);

    const pressurePlot = plotCalls.find(
      (plot) => plot.layout?.title?.text === "Pressure vs Position",
    );
    expect(pressurePlot).toBeDefined();
    expect(pressurePlot?.data[0]?.y).toEqual([100000, 101325, 102500]);
    expect(pressurePlot?.layout?.yaxis).toMatchObject({
      rangemode: "tozero",
      tickformat: ",.0f",
      exponentformat: "none",
    });
  });

  it("applies per-node plot_options.hide_species/show_species to mole fraction traces", () => {
    useConfigStore.setState({
      config: {
        nodes: [
          {
            id: "steady_reactor",
            type: "IdealGasReactor",
            properties: {
              plot_options: {
                hide_species: ["N2"],
                show_species: ["trace_radical"],
              },
            },
          },
        ],
        connections: [],
      },
    });

    const dataWithTrace: SimulationProgress = {
      is_running: false,
      is_complete: true,
      times: [0, 1],
      reactors_series: {
        steady_reactor: {
          T: [1011.31, 1011.31],
          P: [101325, 101325],
          X: {
            O2: [0.2, 0.2],
            N2: [0.7, 0.7],
            // Below MAIN_SPECIES_MIN_FRACTION (1e-4) -- only appears because
            // it's named in show_species.
            trace_radical: [1e-6, 1e-6],
          },
          Y: { O2: [0.23, 0.23], N2: [0.77, 0.77] },
        },
      },
    };

    render(<PlotsTab data={dataWithTrace} />);

    const moleFractionPlot = plotCalls.find((plot) =>
      plot.data.some((trace) => trace.name === "N2" || trace.name === "trace_radical"),
    );
    expect(moleFractionPlot).toBeDefined();

    const n2Trace = moleFractionPlot?.data.find((t) => t.name === "N2");
    const o2Trace = moleFractionPlot?.data.find((t) => t.name === "O2");
    const traceRadical = moleFractionPlot?.data.find(
      (t) => t.name === "trace_radical",
    );

    expect(n2Trace?.visible).toBe("legendonly");
    expect(o2Trace?.visible).toBe(true);
    expect(traceRadical).toBeDefined();
    expect(traceRadical?.visible).toBe(true);
  });
});
