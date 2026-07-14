/**
 * Asserts RunControl split-button modes: Run Simulation, Force Run, and Run Sweep.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { RunControl } from "./RunControl";

vi.mock("@/api/sweep", () => ({
  getSweepInfo: vi.fn().mockResolvedValue({ can_run: false, reason: "No sweep" }),
  getSweepStatus: vi.fn(),
  startSweep: vi.fn(),
}));

const mockToastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: (...args: unknown[]) => mockToastInfo(...args) },
}));

vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: (selector: (s: unknown) => unknown) =>
    selector({ refresh: vi.fn() }),
}));

describe("RunControl", () => {
  const onRunSimulation = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows Force Run in the menu and switches the primary label without Ctrl+Enter", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByLabelText("Choose run action"));
    expect(screen.getByRole("menuitemradio", { name: /force run/i })).toBeInTheDocument();
    expect(screen.getByText("Solve ignoring cache")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitemradio", { name: /force run/i }));
    expect(screen.getByRole("button", { name: "Force Run" })).toBeInTheDocument();
    expect(screen.queryByText(/ctrl\+enter/i)).not.toBeInTheDocument();
  });

  it("calls onRunSimulation(true) when Force Run mode is selected and primary is clicked", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByLabelText("Choose run action"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /force run/i }));
    fireEvent.click(screen.getByRole("button", { name: "Force Run" }));

    expect(onRunSimulation).toHaveBeenCalledOnce();
    expect(onRunSimulation).toHaveBeenCalledWith(true);
  });

  it("calls onRunSimulation(false) for the default Run Simulation mode", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /run simulation/i }));
    expect(onRunSimulation).toHaveBeenCalledWith(false);
  });

  it("nudges toward Ctrl+Enter after repeatedly clicking Run Simulation by mouse", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    const button = screen.getByRole("button", { name: /run simulation/i });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mockToastInfo).not.toHaveBeenCalled();

    fireEvent.click(button);
    expect(mockToastInfo).toHaveBeenCalledOnce();
    expect(mockToastInfo).toHaveBeenCalledWith(expect.stringContaining("Ctrl+Enter"));
  });

  it("does not nudge while in Force Run mode, since Ctrl+Enter doesn't do the same thing", () => {
    render(
      <RunControl
        onRunSimulation={onRunSimulation}
        isRunning={false}
        runDisabled={false}
      />,
    );

    fireEvent.click(screen.getByLabelText("Choose run action"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /force run/i }));
    const button = screen.getByRole("button", { name: "Force Run" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    expect(mockToastInfo).not.toHaveBeenCalled();
  });
});
