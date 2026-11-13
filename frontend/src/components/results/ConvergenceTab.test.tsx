/**
 * Vitest unit tests for ConvergenceTab's conservation summary.
 *
 * Asserts:
 * - A node with `energy_checked: false` (imposed temperature) shows energy as
 *   "not checked (imposed temperature)" with the implied heat in kW, never as
 *   OK or FAILED, even when `energy_closes` is false.
 * - Without the field, a failed energy balance still shows FAILED.
 */

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";
import type { NodeConservation, SimulationProgress } from "@/types/simulation";
import { ConvergenceTab } from "./ConvergenceTab";

vi.mock("react-plotly.js", () => ({ default: () => <div data-testid="plot" /> }));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (state: { theme: "light" }) => unknown) =>
    selector({ theme: "light" }),
}));

vi.mock("@/stores/selectionStore", () => ({
  useSelectionStore: (selector: (state: unknown) => unknown) =>
    selector({ selectedElement: { type: "node", data: { id: "cell" } } }),
}));

const BALANCE: NodeConservation = {
  mass_in_kg_s: 1,
  mass_out_kg_s: 1,
  energy_in_kw: 10,
  energy_out_kw: 12.5,
  mass_closes: true,
  energy_closes: false,
};

function renderWith(conservation: NodeConservation) {
  const data = {
    is_running: false,
    is_complete: true,
    times: [0],
    reactors_series: { cell: { T: [300], P: [101325], X: {}, Y: {}, conservation } },
  } as unknown as SimulationProgress;
  render(<ConvergenceTab data={data} />);
}

describe("ConvergenceTab conservation summary", () => {
  it("shows an imposed-temperature node's energy as not checked, with the implied heat", () => {
    renderWith({ ...BALANCE, energy_checked: false, implied_heat_kw: 2.5 });

    expect(
      screen.getByText(/not checked \(imposed temperature\), implied heat 2\.50 kW/),
    ).toBeInTheDocument();
    expect(screen.queryByText("FAILED")).not.toBeInTheDocument();
    expect(screen.getByText("✓ Mass conservation OK")).toBeInTheDocument();
  });

  it("still reports a failed energy balance when the field is absent", () => {
    renderWith(BALANCE);

    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText("⚠ Conservation check failed")).toBeInTheDocument();
  });
});
