/**
 * Vitest unit tests for PlotsTab.
 *
 * Asserts:
 * - Single-sample steady results are rendered with visible markers.
 */

import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSelectionStore } from "@/stores/selectionStore";
import type { SimulationProgress } from "@/types/simulation";
import { PlotsTab } from "./PlotsTab";

interface PlotTrace {
  mode?: string;
  x?: number[];
  y?: number[];
}

interface PlotProps {
  data: PlotTrace[];
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

describe("PlotsTab", () => {
  beforeEach(() => {
    plotCalls.length = 0;
    useSelectionStore.setState({
      selectedElement: { type: "node", data: { id: "steady_reactor" } },
    });
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
  });
});
