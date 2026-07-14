/**
 * Asserts AddReactorModal: falls back to a fixed type list when /api/ui/kinds
 * hasn't resolved, only shows the Stage picker when the config has more than
 * one stage, pre-selects defaultGroup, and calls addNode with the chosen
 * type/group on submit.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AddReactorModal } from "./AddReactorModal";

let mockNodes: Record<string, unknown>[] = [];
let mockConnections: Record<string, unknown>[] = [];
const mockAddNode = vi.fn();

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({ addNode: mockAddNode, config: { nodes: mockNodes, connections: mockConnections } }),
}));

let mockKinds: { reactors: { kind: string; doc_url: string | null; description: string | null }[] } = {
  reactors: [],
};
vi.mock("@/hooks/useKinds", () => ({
  useKinds: () => mockKinds,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("AddReactorModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNodes = [];
    mockConnections = [];
    mockKinds = { reactors: [] };
  });

  it("falls back to the fixed type list when the kind registry hasn't loaded", () => {
    render(<AddReactorModal open onClose={vi.fn()} />);
    const select = screen.getByLabelText("Type") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(["IdealGasReactor", "IdealGasConstPressureReactor", "Reservoir"]);
  });

  it("uses the dynamic kind list once it resolves, including kinds absent from the fallback", () => {
    mockKinds = {
      reactors: [
        { kind: "IdealGasMoleReactor", doc_url: "https://cantera.org/x", description: "d" },
        { kind: "Reservoir", doc_url: "https://cantera.org/y", description: "d2" },
      ],
    };
    render(<AddReactorModal open onClose={vi.fn()} />);
    // The doc-link tooltip icon adds its own accessible text to the label,
    // so match by prefix rather than the exact string "Type".
    const select = screen.getByLabelText(/^Type/) as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(["IdealGasMoleReactor", "Reservoir"]);
  });

  it("hides the Stage picker when the config has at most one stage", () => {
    mockNodes = [{ id: "r1", group: "only_stage" }];
    render(<AddReactorModal open onClose={vi.fn()} />);
    expect(screen.queryByText("Stage")).not.toBeInTheDocument();
  });

  it("shows the Stage picker pre-selected to defaultGroup when multiple stages exist", () => {
    mockNodes = [
      { id: "r1", group: "stage_a" },
      { id: "r2", group: "stage_b" },
    ];
    render(<AddReactorModal open onClose={vi.fn()} defaultGroup="stage_b" />);
    const select = screen.getByLabelText("Stage") as HTMLSelectElement;
    expect(select.value).toBe("stage_b");
  });

  it("submits addNode with the entered id, type, and stage", () => {
    mockNodes = [
      { id: "r1", group: "stage_a" },
      { id: "r2", group: "stage_b" },
    ];
    render(<AddReactorModal open onClose={vi.fn()} defaultGroup="stage_b" />);

    fireEvent.change(screen.getByLabelText("Reactor ID"), { target: { value: "r3" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(mockAddNode).toHaveBeenCalledWith(
      expect.objectContaining({ id: "r3", type: "IdealGasReactor" }),
      "stage_b",
    );
  });

  it("rejects an empty reactor ID without calling addNode", () => {
    render(<AddReactorModal open onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(mockAddNode).not.toHaveBeenCalled();
  });
});
