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
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { toast } from "sonner";
import { PropertiesPanel } from "./PropertiesPanel";

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
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

let mockPreviewId: string | null = null;
let mockPreviewNodes: Array<{ id: string; properties: Record<string, unknown> }> | null = null;
let mockPreviewConnections: Array<{ id: string; properties: Record<string, unknown> }> | null =
  null;
let mockActiveScenarioId: string | null = null;
let mockPreviewErrorAfterLoad: string | null = null;
const mockLoadScenarioPreview = vi.fn().mockResolvedValue(undefined);
const mockRefreshScenarios = vi.fn();

vi.mock("@/stores/scenarioStore", () => {
  const useScenarioStore = (selector: (s: unknown) => unknown) => {
    const store = {
      previewId: mockPreviewId,
      previewNodes: mockPreviewNodes,
      previewConnections: mockPreviewConnections,
      activeId: mockActiveScenarioId,
      loadPreview: mockLoadScenarioPreview,
      refresh: mockRefreshScenarios,
    };
    return selector(store);
  };
  (useScenarioStore as unknown as { getState: () => unknown }).getState = () => ({
    previewError: mockPreviewErrorAfterLoad,
  });
  return { useScenarioStore };
});

const mockUpdateScenarioEntity = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/scenarios", () => ({
  BASELINE_SCENARIO_ID: "BASELINE",
  updateScenarioEntity: (...args: unknown[]) => mockUpdateScenarioEntity(...args),
}));

let mockKinds: {
  reactors: { kind: string; doc_url: string | null; description: string | null }[];
  connections: { kind: string; doc_url: string | null; description: string | null }[];
} = { reactors: [], connections: [] };

vi.mock("@/hooks/useKinds", () => ({
  useKinds: () => mockKinds,
}));

describe("PropertiesPanel delete confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialConditionsEditNonce = 0;
    mockKinds = { reactors: [], connections: [] };
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

  it("hides underscore-prefixed properties from display", () => {
    // A leading underscore marks a property as private/internal (e.g. a
    // plugin's own display annotation, not a physical input) -- mirrors
    // Python's own convention. Must not appear in the panel, editable or not.
    mockConfig = {
      nodes: [],
      connections: [
        {
          id: "pfr_loss_wall",
          type: "Wall",
          source: "pfr_ambient",
          target: "pfr",
          properties: { area: 1.0, _is_energy_stream: true },
        },
      ],
    } as Record<string, unknown>;
    mockSelectedElement = {
      type: "edge",
      data: { id: "pfr_loss_wall", type: "Wall" },
    };

    render(<PropertiesPanel />);

    expect(screen.getByText("area")).toBeInTheDocument();
    expect(screen.queryByText("_is_energy_stream")).not.toBeInTheDocument();
    expect(screen.queryByText("is_energy_stream")).not.toBeInTheDocument();
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
    mockKinds = { reactors: [], connections: [] };
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
    mockKinds = { reactors: [], connections: [] };
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

describe("PropertiesPanel Cantera doc-link tooltip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialConditionsEditNonce = 0;
    mockKinds = { reactors: [], connections: [] };
    mockPreviewId = null;
    mockPreviewNodes = null;
    mockPreviewConnections = null;
  });

  it("shows a Cantera doc link for a selected reactor kind on hover", () => {
    mockKinds = {
      reactors: [
        {
          kind: "IdealGasReactor",
          doc_url: "https://cantera.org/stable/python/zerodim.html#cantera.IdealGasReactor",
          description: "Ideal-gas, constant-volume reactor.",
        },
      ],
      connections: [],
    };
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

    render(<PropertiesPanel />);

    const trigger = screen.getByLabelText("About IdealGasReactor");
    fireEvent.mouseEnter(trigger.parentElement!);
    const link = screen.getByRole("link", { name: "Cantera docs" });
    expect(link).toHaveAttribute(
      "href",
      "https://cantera.org/stable/python/zerodim.html#cantera.IdealGasReactor",
    );
    expect(screen.getByText("Ideal-gas, constant-volume reactor.")).toBeInTheDocument();
  });

  it("shows a Cantera doc link for a selected connection kind on hover", () => {
    mockKinds = {
      reactors: [],
      connections: [
        {
          kind: "MassFlowController",
          doc_url: "https://cantera.org/stable/python/zerodim.html#cantera.MassFlowController",
          description: "Imposes a fixed or time-varying mass flow rate between two reactors.",
        },
      ],
    };
    mockSelectedElement = {
      type: "edge",
      data: {
        id: "mfc_1",
        type: "MassFlowController",
        source: "reactor_1",
        target: "reactor_2",
      },
    };
    mockConfig = {
      nodes: [],
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

    render(<PropertiesPanel />);

    const trigger = screen.getByLabelText("About MassFlowController");
    fireEvent.mouseEnter(trigger.parentElement!);
    const link = screen.getByRole("link", { name: "Cantera docs" });
    expect(link).toHaveAttribute(
      "href",
      "https://cantera.org/stable/python/zerodim.html#cantera.MassFlowController",
    );
  });

  it("omits the doc-link icon when the kind has no doc_url (e.g. plugin types)", () => {
    mockKinds = {
      reactors: [
        { kind: "_TestPluginReactor", doc_url: null, description: null },
      ],
      connections: [],
    };
    mockSelectedElement = {
      type: "node",
      data: { id: "plugin_r", type: "_TestPluginReactor" },
    };
    mockConfig = {
      nodes: [{ id: "plugin_r", type: "_TestPluginReactor", properties: {} }],
      connections: [],
    };

    render(<PropertiesPanel />);

    expect(screen.queryByLabelText("About _TestPluginReactor")).not.toBeInTheDocument();
    expect(screen.getByText("_TestPluginReactor")).toBeInTheDocument();
  });
});

describe("PropertiesPanel scenario preview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialConditionsEditNonce = 0;
    mockKinds = { reactors: [], connections: [] };
    mockSelectedElement = {
      type: "node",
      data: { id: "reactor_1", type: "IdealGasReactor" },
    };
    mockConfig = {
      nodes: [
        {
          id: "reactor_1",
          type: "IdealGasReactor",
          properties: { temperature: 1273.15, length: 0.3 },
        },
      ],
      connections: [],
    };
    mockPreviewId = null;
    mockPreviewNodes = null;
    mockPreviewConnections = null;
    mockActiveScenarioId = null;
    mockPreviewErrorAfterLoad = null;
  });

  it("shows no override styling when nothing is previewed", () => {
    render(<PropertiesPanel />);

    expect(screen.getByText("0.30")).toBeInTheDocument();
  });

  it("shows a scenario's overridden value once it's selected", () => {
    mockPreviewId = "C600_P300";
    mockPreviewNodes = [
      { id: "reactor_1", properties: { temperature: 1273.15, length: 0.6 } },
    ];
    mockPreviewConnections = [];

    render(<PropertiesPanel />);

    expect(screen.getByText("0.60")).toBeInTheDocument();
    expect(screen.queryByText("0.30")).not.toBeInTheDocument();
  });

  it("never names the previewed scenario in this panel", () => {
    // The panel shows the element's own identity (id + kind); which scenario
    // is being previewed belongs to the Scenario Pane, not here. Overridden
    // values are still flagged per-field by the amber styling below.
    mockPreviewId = "C600_P300";
    mockPreviewNodes = [
      { id: "reactor_1", properties: { temperature: 1273.15, length: 0.6 } },
    ];
    mockPreviewConnections = [];

    render(<PropertiesPanel />);

    expect(screen.queryByText(/Previewing scenario/)).not.toBeInTheDocument();
    expect(screen.queryByText("C600_P300")).not.toBeInTheDocument();
  });

  it("still shows the element kind when a scenario auto-selected it by id alone", () => {
    // scenarioStore.setActive selects a reactor with `data: {id}` only -- no
    // `type` -- so the kind must come from the config entry or the heading
    // renders blank while previewing.
    mockSelectedElement = { type: "node", data: { id: "reactor_1" } };
    mockPreviewId = "C600_P300";
    mockPreviewNodes = [
      { id: "reactor_1", properties: { temperature: 1273.15, length: 0.6 } },
    ];
    mockPreviewConnections = [];

    render(<PropertiesPanel />);

    expect(screen.getByText("IdealGasReactor")).toBeInTheDocument();
  });

  it("does not highlight a field the scenario leaves unchanged", () => {
    mockPreviewId = "C600_P300";
    // Same length as the base — only temperature differs.
    mockPreviewNodes = [
      { id: "reactor_1", properties: { temperature: 900, length: 0.3 } },
    ];
    mockPreviewConnections = [];

    render(<PropertiesPanel />);

    const lengthValue = screen.getByText("0.30");
    expect(lengthValue.className).not.toMatch(/amber/);
  });

  it("highlights an overridden field distinctly from an unchanged one", () => {
    mockPreviewId = "C600_P300";
    mockPreviewNodes = [
      { id: "reactor_1", properties: { temperature: 1273.15, length: 0.6 } },
    ];
    mockPreviewConnections = [];

    render(<PropertiesPanel />);

    expect(screen.getByText("0.60").className).toMatch(/amber/);
  });

  it("editing still shows/edits the base value, not the previewed scenario's override", () => {
    mockPreviewId = "C600_P300";
    mockPreviewNodes = [
      { id: "reactor_1", properties: { temperature: 1273.15, length: 0.6 } },
    ];
    mockPreviewConnections = [];

    render(<PropertiesPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByDisplayValue("0.3")).toBeInTheDocument();
  });

  it("saves into the active scenario's overlay (not the base) and surfaces a failed preview instead of a plain success toast", async () => {
    mockActiveScenarioId = "C1T";
    // The write can succeed while the resulting merged config is invalid
    // (e.g. a cross-node consistency rule) -- loadPreview swallows that into
    // previewError rather than rejecting, so it must be surfaced explicitly.
    mockPreviewErrorAfterLoad = "STONE v2 error: conflicting process pressures";

    render(<PropertiesPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByDisplayValue("0.3"), { target: { value: "0.6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockUpdateScenarioEntity).toHaveBeenCalledWith("C1T", "reactor_1", { length: 0.6 }),
    );
    expect(mockUpdateNode).not.toHaveBeenCalled();
    await waitFor(() => expect(mockLoadScenarioPreview).toHaveBeenCalledWith("C1T"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("no longer previews cleanly"),
      ),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("toasts a plain success when the scenario overlay save previews cleanly", async () => {
    mockActiveScenarioId = "C1T";
    mockPreviewErrorAfterLoad = null;

    render(<PropertiesPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByDisplayValue("0.3"), { target: { value: "0.6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Scenario "C1T" overlay updated'),
    );
    expect(toast.error).not.toHaveBeenCalled();
  });
});
