/**
 * Vitest unit tests for SankeyTab.
 *
 * Asserts:
 * - Sankey node bars use Cytoscape temperature colors, not Plotly defaults.
 */

import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { temperatureToNodeColor } from "@/lib/cytoscapeNodeColor";
import type { SimulationResults } from "@/types/simulation";
import { SankeyTab } from "./SankeyTab";

interface SankeyNodeTrace {
  label?: string[];
  color?: string[];
}

interface SankeyPlotTrace {
  type?: string;
  node?: SankeyNodeTrace;
}

interface PlotProps {
  data: SankeyPlotTrace[];
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

const baseResults: SimulationResults = {
  is_running: false,
  is_complete: true,
  times: [0],
  reactors_series: {},
  sankey_nodes: ["feed", "reactor", "outlet"],
  sankey_links: {
    source: [0, 1],
    target: [1, 2],
    value: [1, 1],
    color: ["mass", "mass"],
    label: ["mass", "mass"],
  },
  reactor_reports: {
    feed: { T: 300 },
    reactor: { T: 1500 },
    outlet: { T: 1200 },
  },
};

describe("SankeyTab", () => {
  beforeEach(() => {
    plotCalls.length = 0;
  });

  it("sets node colors from reactor temperatures matching the Cytoscape scale", () => {
    render(<SankeyTab results={baseResults} />);

    const node = plotCalls[0].data[0].node;
    expect(node?.color).toEqual([
      temperatureToNodeColor(300, "light"),
      temperatureToNodeColor(1500, "light"),
      temperatureToNodeColor(1200, "light"),
    ]);
  });
});
