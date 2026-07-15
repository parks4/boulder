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
const mockUpdateNode = vi.fn();
const mockUpdateConnection = vi.fn();
const mockClearSelection = vi.fn();
let mockSelectedElement: {
  type: "node" | "edge";
  data: Record<string, unknown>;
} | null = null;
let mockInitialConditionsEditNonce = 0;
let mockConfig: Record<string, unknown> = {
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
      initialConditionsEditNonce: mockInitialConditionsEditNonce,
      clearSelection: mockClearSelection,
    };
    return selector(store);
  },
}));

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) => {
    const store = {
      config: mockConfig,
      updateNode: mockUpdateNode,
      updateConnection: mockUpdateConnection,
      removeNode: mockRemoveNode,
      removeConnection: mockRemoveConnection,
    };
    return selector(store);
  },
}));

describe("PropertiesPanel delete confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialConditionsEditNonce = 0;
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

  it("unfolds nested initial conditions for display", () => {
    mockConfig = {
      nodes: [
        {
          id: "cpr_0",
          type: "IdealGasConstPressureReactor",
          properties: {
            volume: 2.35,
            initial: {
              temperature: 1001.0,
              pressure: 101325.0,
              composition: "H2:2,O2:1,N2:4",
            },
          },
        },
      ],
      connections: [],
    } as Record<string, unknown>;
    mockSelectedElement = {
      type: "node",
      data: { id: "cpr_0", type: "IdealGasConstPressureReactor" },
    };

    render(<PropertiesPanel />);

    expect(screen.getByText("727.85 °C")).toBeInTheDocument();
    expect(screen.getByText("101,325.00")).toBeInTheDocument();
    expect(screen.getByText("H2:2,O2:1,N2:4")).toBeInTheDocument();
    expect(screen.queryByText("initial")).not.toBeInTheDocument();
  });

  it("defaults to the sole stage's panel when nothing is selected and the config has one stage", () => {
    mockSelectedElement = null;
    mockConfig = {
      nodes: [{ id: "r1", type: "IdealGasReactor", group: "default", properties: {} }],
      connections: [],
    };

    render(<PropertiesPanel />);

    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByText("Stage")).toBeInTheDocument();
    expect(
      screen.queryByText("Click a node or edge in the graph to view its properties."),
    ).not.toBeInTheDocument();
  });

  it("shows the plain placeholder when nothing is selected and the config has multiple stages", () => {
    mockSelectedElement = null;
    mockConfig = {
      nodes: [
        { id: "r1", type: "IdealGasReactor", group: "stage_a", properties: {} },
        { id: "r2", type: "IdealGasReactor", group: "stage_b", properties: {} },
      ],
      connections: [],
    };

    render(<PropertiesPanel />);

    expect(
      screen.getByText("Click a node or edge in the graph to view its properties."),
    ).toBeInTheDocument();
  });
});

describe("PropertiesPanel edit-on-double-click", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialConditionsEditNonce = 0;
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
      connections: [],
    };
  });

  it("enters edit mode when selection requests editInitialConditions", () => {
    mockInitialConditionsEditNonce = 1;
    mockSelectedElement = {
      type: "node",
      data: { id: "reactor_1", type: "IdealGasReactor" },
    };

    render(<PropertiesPanel />);

    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("1000.00")).toBeInTheDocument();
  });

  it("shows view mode for a normal single-click selection", () => {
    render(<PropertiesPanel />);

    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByText("1000.00 °C")).toBeInTheDocument();
  });
});

describe("PropertiesPanel object-valued properties", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialConditionsEditNonce = 0;
    mockSelectedElement = {
      type: "node",
      data: { id: "reactor_1", type: "ConstPressureReactor" },
    };
    mockConfig = {
      nodes: [
        {
          id: "reactor_1",
          type: "ConstPressureReactor",
          properties: {
            volume: 1.0,
            // Declared before `initial` so the ordering test below actually
            // exercises the "move to the end" re-insertion, not just a
            // dict that already happened to have it last.
            plot_options: { hide_species: ["N2", "O2"], show_species: ["e", "OH"] },
            initial: { temperature: 1273.15, pressure: 101325.0 },
          },
        },
      ],
      connections: [],
    };
  });

  it("renders an object-valued property as JSON text, not [object Object]", () => {
    render(<PropertiesPanel />);

    expect(
      screen.getByText('{"hide_species":["N2","O2"],"show_species":["e","OH"]}'),
    ).toBeInTheDocument();
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
  });

  it("shows JSON text (not [object Object]) in the edit-mode input", () => {
    render(<PropertiesPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(
      screen.getByDisplayValue('{"hide_species":["N2","O2"],"show_species":["e","OH"]}'),
    ).toBeInTheDocument();
  });

  it("round-trips the object back through Save without corrupting it to a string", () => {
    render(<PropertiesPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mockUpdateNode).toHaveBeenCalledWith(
      "reactor_1",
      expect.objectContaining({
        properties: expect.objectContaining({
          plot_options: { hide_species: ["N2", "O2"], show_species: ["e", "OH"] },
        }),
      }),
    );
  });

  it("renders plot_options last, after unfolded initial-condition fields", () => {
    render(<PropertiesPanel />);

    const labels = screen
      .getAllByText(/^(volume|plot_options|temperature|pressure)/i)
      .map((el) => el.textContent);
    const plotIndex = labels.findIndex((t) => /^plot_options/i.test(t ?? ""));
    const temperatureIndex = labels.findIndex((t) => /^temperature/i.test(t ?? ""));
    const pressureIndex = labels.findIndex((t) => /^pressure/i.test(t ?? ""));

    expect(plotIndex).toBeGreaterThan(-1);
    expect(plotIndex).toBeGreaterThan(temperatureIndex);
    expect(plotIndex).toBeGreaterThan(pressureIndex);
  });
});
