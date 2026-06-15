/**
 * Vitest unit tests for PropertiesPanel delete confirmation.
 *
 * Asserts:
 * - Clicking Delete on a node opens the confirmation modal instead of deleting immediately.
 * - Cancel closes the modal without calling removeNode.
 * - Confirm calls removeNode, clears selection, and closes the modal.
 * - Clicking Delete on a connection deletes immediately without showing the modal.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PropertiesPanel } from "./PropertiesPanel";

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), success: vi.fn() },
}));

const mockRemoveNode = vi.fn();
const mockRemoveConnection = vi.fn();
const mockClearSelection = vi.fn();
let mockSelectedElement: {
  type: "node" | "edge";
  data: Record<string, unknown>;
} | null = null;
let mockConfig = {
  nodes: [
    {
      id: "reactor_1",
      type: "IdealGasReactor",
      properties: { temperature: 1273.15, pressure: 101325 },
    },
  ],
  connections: [
    {
      id: "mfc_1",
      type: "MassFlowController",
      source: "reactor_1",
      target: "reactor_2",
      properties: { mdot: 0.001 },
    },
  ],
};

vi.mock("@/stores/selectionStore", () => ({
  useSelectionStore: (selector: (s: unknown) => unknown) => {
    const store = {
      selectedElement: mockSelectedElement,
      clearSelection: mockClearSelection,
    };
    return selector(store);
  },
}));

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) => {
    const store = {
      config: mockConfig,
      updateNode: vi.fn(),
      updateConnection: vi.fn(),
      removeNode: mockRemoveNode,
      removeConnection: mockRemoveConnection,
    };
    return selector(store);
  },
}));

describe("PropertiesPanel delete confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSelectedElement = {
      type: "node",
      data: { id: "reactor_1", type: "IdealGasReactor" },
    };
    mockConfig = {
      nodes: [
        {
          id: "reactor_1",
          type: "IdealGasReactor",
          properties: { temperature: 1273.15, pressure: 101325 },
        },
      ],
      connections: [
        {
          id: "mfc_1",
          type: "MassFlowController",
          source: "reactor_1",
          target: "reactor_2",
          properties: { mdot: 0.001 },
        },
      ],
    };
  });

  it("opens confirmation modal when deleting a node", () => {
    render(<PropertiesPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(screen.getByText("Delete node?")).toBeInTheDocument();
    expect(mockRemoveNode).not.toHaveBeenCalled();
  });

  it("does not delete a node when Cancel is clicked", () => {
    render(<PropertiesPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByText("Delete node?")).not.toBeInTheDocument();
    expect(mockRemoveNode).not.toHaveBeenCalled();
  });

  it("deletes a node when Delete is confirmed", () => {
    render(<PropertiesPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(document.getElementById("confirm-delete-node")!);

    expect(mockRemoveNode).toHaveBeenCalledWith("reactor_1");
    expect(mockClearSelection).toHaveBeenCalled();
    expect(screen.queryByText("Delete node?")).not.toBeInTheDocument();
  });

  it("deletes a connection immediately without confirmation", () => {
    mockSelectedElement = {
      type: "edge",
      data: {
        id: "mfc_1",
        type: "MassFlowController",
        source: "reactor_1",
        target: "reactor_2",
      },
    };

    render(<PropertiesPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(screen.queryByText("Delete node?")).not.toBeInTheDocument();
    expect(mockRemoveConnection).toHaveBeenCalledWith("mfc_1");
    expect(mockClearSelection).toHaveBeenCalled();
  });
});
