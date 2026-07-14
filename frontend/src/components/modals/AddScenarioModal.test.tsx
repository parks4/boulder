/**
 * Asserts AddScenarioModal's "Start from" clone-base list is sourced from
 * authoredIds (every scenario in the config) rather than the HDF5-derived
 * `scenarios` list — otherwise a scenario created since the last sweep can't
 * be used as a clone base.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AddScenarioModal } from "./AddScenarioModal";

const mockCreateScenario = vi.fn();
let mockScenarios: Array<{ id: string; label: string }> = [];
let mockAuthoredIds: string[] = [];

vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: (selector: (s: unknown) => unknown) =>
    selector({ scenarios: mockScenarios, authoredIds: mockAuthoredIds, createScenario: mockCreateScenario }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("AddScenarioModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockScenarios = [{ id: "A", label: "Scenario A" }];
    mockAuthoredIds = ["A", "B"];
  });

  it("lists every authored scenario as a clone base, not just swept ones", () => {
    render(<AddScenarioModal open onClose={vi.fn()} onCreated={vi.fn()} />);
    const select = screen.getByLabelText(/start from/i) as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.textContent);
    expect(options).toContain("Clone of Scenario A");
    // "B" has no swept metadata (no label) yet, so it falls back to its id —
    // this is exactly the case the fix targets: a created-but-unswept scenario.
    expect(options).toContain("Clone of B");
  });

  it("does not list scenarios that no longer exist in the config", () => {
    mockAuthoredIds = ["A"];
    render(<AddScenarioModal open onClose={vi.fn()} onCreated={vi.fn()} />);
    const select = screen.getByLabelText(/start from/i) as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.textContent);
    expect(options).not.toContain("Clone of B");
  });
});
