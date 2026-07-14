/**
 * Asserts SolverDetailsModal shows a Cantera doc-link tooltip for the
 * selected solver kind, and that it updates when the kind changes.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SolverDetailsModal } from "./SolverDetailsModal";
import { STEADY_KINDS } from "./solverShared";

function renderModal(kind: (typeof STEADY_KINDS)[number] = "advance_to_steady_state") {
  return render(
    <SolverDetailsModal
      open
      onClose={vi.fn()}
      mode="steady"
      kind={kind}
      kinds={STEADY_KINDS}
      onKindChange={vi.fn()}
      rtol="1e-9"
      onRtolChange={vi.fn()}
      atol="1e-15"
      onAtolChange={vi.fn()}
      maxSteps="10000"
      onMaxStepsChange={vi.fn()}
      simTime="10"
      onSimTimeChange={vi.fn()}
      timeStep="1"
      onTimeStepChange={vi.fn()}
    />,
  );
}

describe("SolverDetailsModal doc-link tooltip", () => {
  it("shows a Cantera doc link for the selected kind on hover", () => {
    renderModal("advance_to_steady_state");
    const trigger = screen.getByLabelText("About advance_to_steady_state");
    fireEvent.mouseEnter(trigger.parentElement!);
    const link = screen.getByRole("link", { name: "Cantera docs" });
    expect(link).toHaveAttribute(
      "href",
      "https://cantera.org/stable/python/zerodim.html#cantera.ReactorNet.advance_to_steady_state",
    );
  });

  it("points at a different anchor for solve_steady", () => {
    renderModal("solve_steady");
    const trigger = screen.getByLabelText("About solve_steady");
    fireEvent.mouseEnter(trigger.parentElement!);
    const link = screen.getByRole("link", { name: "Cantera docs" });
    expect(link).toHaveAttribute(
      "href",
      "https://cantera.org/stable/python/zerodim.html#cantera.ReactorNet.solve_steady",
    );
  });
});
