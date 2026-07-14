/**
 * Asserts RunControl split-button modes: Run Simulation, Force Run, and Run Sweep.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { RunControl } from "./RunControl";

const mockGetSweepInfo = vi
  .fn()
  .mockResolvedValue({ can_run: false, reason: "No sweep" });
vi.mock("@/api/sweep", () => ({
  getSweepInfo: (...args: unknown[]) => mockGetSweepInfo(...args),
  getSweepStatus: vi.fn(),
  startSweep: vi.fn(),
}));

const mockToastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: (...args: unknown[]) => mockToastInfo(...args) },
}));

let mockScenarioRevision = 0;
vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: (selector: (s: unknown) => unknown) =>
    selector({ refresh: vi.fn(), revision: mockScenarioRevision }),
}));

describe("RunControl", () => {
  const onRunSimulation = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSweepInfo.mockResolvedValue({ can_run: false, reason: "No sweep" });
    mockScenarioRevision = 0;
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

  it("re-fetches sweep info when a scenario is added/edited/renamed/deleted elsewhere", async () => {
    const { rerender } = render(
      <RunControl onRunSimulation={onRunSimulation} isRunning={false} runDisabled={false} />,
    );
    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalledOnce());

    mockGetSweepInfo.mockResolvedValue({ can_run: true, n_scenarios: 3, reason: "Run 3 scenarios" });
    mockScenarioRevision += 1;
    rerender(
      <RunControl onRunSimulation={onRunSimulation} isRunning={false} runDisabled={false} />,
    );

    await waitFor(() => expect(mockGetSweepInfo).toHaveBeenCalledTimes(2));
  });
});
