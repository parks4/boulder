/**
 * Vitest unit tests for ThermoReportTab.
 *
 * Asserts the empty-reports message tells the truth about whether a
 * simulation has actually run -- see the regression this pins below.
 */

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { SimulationResults } from "@/types/simulation";
import { useSelectionStore } from "@/stores/selectionStore";
import { useConfigStore } from "@/stores/configStore";
import { ThermoReportTab } from "./ThermoReportTab";

const baseResults: SimulationResults = {
  is_running: false,
  is_complete: true,
  times: [0],
  reactors_series: { combustor: { T: [1500], P: [101325], X: {} } },
  reactor_reports: {},
};

afterEach(() => {
  useSelectionStore.setState({ selectedElement: null });
});

describe("ThermoReportTab empty-reports message", () => {
  it("says the result has no thermo data when the simulation is complete", () => {
    useSelectionStore.setState({
      selectedElement: { type: "node", data: { id: "combustor" } },
    });
    render(<ThermoReportTab results={{ ...baseResults, is_complete: true }} />);
    expect(screen.getByText("This result has no thermo report data.")).toBeInTheDocument();
    expect(screen.queryByText(/Run a simulation/)).not.toBeInTheDocument();
  });

  it("still prompts to run a simulation when nothing has run yet", () => {
    useSelectionStore.setState({
      selectedElement: { type: "node", data: { id: "combustor" } },
    });
    render(<ThermoReportTab results={{ ...baseResults, is_complete: false }} />);
    expect(
      screen.getByText("No thermo reports. Run a simulation to see details."),
    ).toBeInTheDocument();
  });

  it("prompts to select an element when nothing is selected, regardless of completion", () => {
    render(<ThermoReportTab results={{ ...baseResults, is_complete: true }} />);
    expect(
      screen.getByText("Select a node or Mass Flow Controller to view thermo details."),
    ).toBeInTheDocument();
  });

  it("still renders the real report once reactor_reports has data", () => {
    useSelectionStore.setState({
      selectedElement: { type: "node", data: { id: "combustor" } },
    });
    useConfigStore.setState({
      config: { nodes: [], connections: [] } as unknown as ReturnType<
        typeof useConfigStore.getState
      >["config"],
    });
    render(
      <ThermoReportTab
        results={{
          ...baseResults,
          is_complete: true,
          reactor_reports: {
            combustor: { reactor_report: "Temperature: 1226.85 °C\nPressure: 1.01e+05 Pa" },
          },
        }}
      />,
    );
    expect(screen.getByText(/Temperature: 1226.85/)).toBeInTheDocument();
  });
});
