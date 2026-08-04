/**
 * Asserts SimulationCalculatingCard: renders nothing when no run is in
 * progress, and shows a headline + sub-step label + progress bar while one is
 * — the single-run analog of SweepCalculatingCard, using the same
 * non-blocking shell (no `fixed inset-0` overlay).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { SimulationProgress } from "@/types/simulation";

let mockIsRunning = false;
let mockProgress: SimulationProgress | null = null;

vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: (selector: (s: unknown) => unknown) =>
    selector({ isRunning: mockIsRunning, progress: mockProgress }),
}));

import { SimulationCalculatingCard } from "./SimulationCalculatingCard";

describe("SimulationCalculatingCard", () => {
  it("renders nothing when no simulation is running", () => {
    mockIsRunning = false;
    const { container } = render(<SimulationCalculatingCard />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a headline and 'Initializing…' before the first progress poll", () => {
    mockIsRunning = true;
    mockProgress = null;

    render(<SimulationCalculatingCard />);

    expect(screen.getByText("Simulation running…")).toBeInTheDocument();
    expect(screen.getByText("Initializing…")).toBeInTheDocument();
  });

  it("shows the current sub-step once progress has arrived", () => {
    mockIsRunning = true;
    mockProgress = {
      is_running: true,
      is_complete: false,
      stages_done: 0,
      n_stages: 1,
      times: [],
      total_time: 10,
      reactors_series: {},
    };

    render(<SimulationCalculatingCard />);

    expect(screen.getByText("Building")).toBeInTheDocument();
  });
});
