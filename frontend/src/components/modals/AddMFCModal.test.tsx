/**
 * Asserts AddMFCModal: falls back to a fixed type list when /api/ui/kinds
 * hasn't resolved, pre-fills the source node from a right-clicked reactor,
 * only shows the Stage picker for multi-stage configs, and calls
 * addConnection with the chosen type/group on submit.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AddMFCModal } from "./AddMFCModal";

let mockNodes: Record<string, unknown>[] = [
  { id: "torch", group: "stage_a" },
  { id: "psr", group: "stage_a" },
];
const mockAddConnection = vi.fn();

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({
      addConnection: mockAddConnection,
      config: { nodes: mockNodes, connections: [] },
    }),
}));

let mockKinds: { connections: { kind: string; doc_url: string | null; description: string | null }[] } = {
  connections: [],
};
vi.mock("@/hooks/useKinds", () => ({
  useKinds: () => mockKinds,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("AddMFCModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNodes = [
      { id: "torch", group: "stage_a" },
      { id: "psr", group: "stage_a" },
    ];
    mockKinds = { connections: [] };
  });

  it("falls back to the fixed type list when the kind registry hasn't loaded", () => {
    render(<AddMFCModal open onClose={vi.fn()} />);
    const select = screen.getByLabelText("Type") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(["MassFlowController", "Valve", "Wall"]);
  });

  it("uses the dynamic kind list once it resolves, including kinds absent from the fallback", () => {
    mockKinds = {
      connections: [{ kind: "PressureController", doc_url: "https://cantera.org/x", description: "d" }],
    };
    render(<AddMFCModal open onClose={vi.fn()} />);
    // The doc-link tooltip icon adds its own accessible text to the label,
    // so match by prefix rather than the exact string "Type".
    const select = screen.getByLabelText(/^Type/) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["PressureController"]);
  });

  it("pre-fills the source node from defaultSource", () => {
    render(<AddMFCModal open onClose={vi.fn()} defaultSource="torch" />);
    const source = screen.getByLabelText("Source") as HTMLSelectElement;
    expect(source.value).toBe("torch");
  });

  it("hides the Stage picker when the config has at most one stage", () => {
    render(<AddMFCModal open onClose={vi.fn()} />);
    expect(screen.queryByText("Stage")).not.toBeInTheDocument();
  });

  it("shows the Stage picker pre-selected to defaultGroup when multiple stages exist", () => {
    mockNodes = [
      { id: "torch", group: "stage_a" },
      { id: "psr", group: "stage_b" },
    ];
    render(<AddMFCModal open onClose={vi.fn()} defaultGroup="stage_b" />);
    const select = screen.getByLabelText("Stage") as HTMLSelectElement;
    expect(select.value).toBe("stage_b");
  });

  it("submits addConnection with the entered id, source, target, and stage", () => {
    mockNodes = [
      { id: "torch", group: "stage_a" },
      { id: "psr", group: "stage_b" },
    ];
    render(
      <AddMFCModal open onClose={vi.fn()} defaultGroup="stage_b" defaultSource="torch" />,
    );

    fireEvent.change(screen.getByLabelText("Connection ID"), { target: { value: "mfc_1" } });
    fireEvent.change(screen.getByLabelText("Target"), { target: { value: "psr" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(mockAddConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "mfc_1",
        type: "MassFlowController",
        source: "torch",
        target: "psr",
      }),
      "stage_b",
    );
  });

  it("rejects a missing target without calling addConnection", () => {
    render(<AddMFCModal open onClose={vi.fn()} defaultSource="torch" />);
    fireEvent.change(screen.getByLabelText("Connection ID"), { target: { value: "mfc_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(mockAddConnection).not.toHaveBeenCalled();
  });
});
