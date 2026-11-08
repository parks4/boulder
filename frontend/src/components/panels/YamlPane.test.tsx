/**
 * Asserts YamlPane: syncs the merged YAML on mount when the canvas has
 * unsynced edits (and shows the original YAML as is, with no sync, when it
 * has none), gates Save on an actual
 * edit, applies Save via parseYaml -> setConfig, Cancel reverts unsaved
 * edits, Download triggers a client-side file download, Ctrl+S saves, and
 * closing confirms only when there's something to lose. Also covers the
 * live one-way refresh: a config change made elsewhere (e.g. adding a
 * reactor) updates the displayed YAML automatically, but never while the
 * user has an unsaved edit sitting in the editor.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { YamlPane } from "./YamlPane";

vi.mock("@monaco-editor/react", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (v: string) => void;
  }) => (
    <textarea
      data-testid="monaco-stub"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

let mockConfig: Record<string, unknown> = {
  nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }],
  connections: [],
};
let mockOriginalYaml = "original: yaml\n";
let mockFileName: string | null = "test.yaml";
let mockDirty = true;
const mockSetConfig = vi.fn();

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({
      config: mockConfig,
      originalYaml: mockOriginalYaml,
      fileName: mockFileName,
      dirty: mockDirty,
      setConfig: mockSetConfig,
    }),
}));

const mockCloseYamlPane = vi.fn();
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: unknown) => unknown) =>
    selector({ closeYamlPane: mockCloseYamlPane }),
}));

const mockResetForNewConfig = vi.fn();
vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: {
    getState: () => ({ resetForNewConfig: mockResetForNewConfig, overlays: {} }),
  },
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: unknown) => unknown) => selector({ theme: "light" }),
}));

let mockIsRunning = false;
vi.mock("@/stores/simulationStore", () => ({
  useSimulationStore: (selector: (s: unknown) => unknown) =>
    selector({ isRunning: mockIsRunning }),
}));

let mockSweeping = false;
vi.mock("@/stores/sweepStore", () => ({
  useSweepRunStore: (selector: (s: unknown) => unknown) => selector({ sweeping: mockSweeping }),
}));

const mockSyncConfig = vi.fn();
const mockParseYaml = vi.fn();
const mockFetchResolvedYaml = vi.fn();
vi.mock("@/api/configs", () => ({
  syncConfig: (...args: unknown[]) => mockSyncConfig(...args),
  parseYaml: (...args: unknown[]) => mockParseYaml(...args),
  fetchResolvedYaml: (...args: unknown[]) => mockFetchResolvedYaml(...args),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

async function editorValue() {
  return (await screen.findByTestId("monaco-stub")) as HTMLTextAreaElement;
}

function saveButton() {
  return screen.getByRole("button", { name: "Save" });
}

describe("YamlPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig = {
      nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }],
      connections: [],
    };
    mockOriginalYaml = "original: yaml\n";
    mockFileName = "test.yaml";
    mockDirty = true;
    mockSyncConfig.mockResolvedValue({ yaml: "merged: yaml\n", warnings: [] });
    mockIsRunning = false;
    mockSweeping = false;
  });

  it("syncs the merged YAML on mount", async () => {
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    expect(mockSyncConfig).toHaveBeenCalledWith(mockConfig, mockOriginalYaml);
  });

  it("shows the original YAML without syncing when the canvas has no unsynced edit", async () => {
    mockDirty = false;
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("original: yaml\n"));
    // A sync would make the server adopt the merged text as its live config.
    expect(mockSyncConfig).not.toHaveBeenCalled();
    expect(saveButton()).toBeDisabled();
  });

  it("shows non-blocking sync warnings", async () => {
    mockSyncConfig.mockResolvedValue({ yaml: "merged: yaml\n", warnings: ["watch out"] });
    render(<YamlPane />);
    expect(await screen.findByText("watch out")).toBeInTheDocument();
  });

  it("Save is disabled until the editor content actually changes", async () => {
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    expect(saveButton()).toBeDisabled();

    fireEvent.change(editor, { target: { value: "merged: yaml\nextra: 1\n" } });
    expect(saveButton()).not.toBeDisabled();
  });

  it("Save parses the edited YAML and applies it to the config store", async () => {
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "merged: yaml\nextra: 1\n" } });

    const parsedConfig = { nodes: [], connections: [] };
    mockParseYaml.mockResolvedValue({ config: parsedConfig, yaml: "merged: yaml\nextra: 1\n" });
    fireEvent.click(saveButton());

    await waitFor(() =>
      expect(mockSetConfig).toHaveBeenCalledWith(
        parsedConfig,
        undefined,
        "merged: yaml\nextra: 1\n",
      ),
    );
    expect(mockParseYaml).toHaveBeenCalledWith("merged: yaml\nextra: 1\n");
    // A save that round-trips exactly what's on screen needs no re-sync.
    expect(saveButton()).toBeDisabled();
    // The base config was just replaced -- drops stale scenario overlays and
    // re-seeds from the new config's own `scenarios:` block.
    expect(mockResetForNewConfig).toHaveBeenCalledOnce();
  });

  it.each([
    // Valid YAML, rejected by the model rules: not a YAML problem.
    ["Unknown node type 'Foo'", "Model rejected: Unknown node type 'Foo'"],
    // A real syntax error: the backend already prefixes it.
    ["Invalid YAML: mapping values are not allowed", "Invalid YAML: mapping values are not allowed"],
  ])("words a 422 save error %j without the raw API prefix", async (detail, shown) => {
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "merged: yaml\nextra: 1\n" } });

    mockParseYaml.mockRejectedValue(new ApiError(422, detail));
    fireEvent.click(saveButton());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(shown));
  });

  it("Cancel reverts unsaved edits back to the last synced value", async () => {
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "scratch\n" } });
    expect(editor).toHaveValue("scratch\n");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(editor).toHaveValue("merged: yaml\n");
    expect(saveButton()).toBeDisabled();
  });

  it("Download serves the server's full resolved YAML, not the editor text", async () => {
    mockFetchResolvedYaml.mockResolvedValue({
      yaml: "resolved: from unfolded\n",
      filename: "config.yaml",
    });
    const createObjectURL = vi.fn((blob: Blob) => `blob:mock-url-${blob.size}`);
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "unsaved edit\n" } });

    fireEvent.click(screen.getByRole("button", { name: "Download" }));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce());
    expect(mockFetchResolvedYaml).toHaveBeenCalledWith({});
    // The downloaded blob is the server's text (not "unsaved edit\n").
    expect(createObjectURL.mock.calls[0][0].size).toBe("resolved: from unfolded\n".length);
    expect(clickSpy).toHaveBeenCalledOnce();
    clickSpy.mockRestore();
  });

  it("Ctrl+S saves when there are unsaved edits", async () => {
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "scratch\n" } });

    mockParseYaml.mockResolvedValue({ config: { nodes: [], connections: [] }, yaml: "scratch\n" });
    fireEvent.keyDown(window, { key: "s", ctrlKey: true });

    await waitFor(() => expect(mockParseYaml).toHaveBeenCalledWith("scratch\n"));
  });

  it("Ctrl+S is a no-op when there's nothing unsaved", async () => {
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));

    fireEvent.keyDown(window, { key: "s", ctrlKey: true });
    expect(mockParseYaml).not.toHaveBeenCalled();
  });

  it("locks Save and shows a banner while a sweep is running", async () => {
    mockSweeping = true;
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "merged: yaml\nextra: 1\n" } });

    expect(saveButton()).toBeDisabled();
    expect(
      screen.getByText(/calculation is running.*locked until it finishes/i),
    ).toBeInTheDocument();
  });

  it("locks Save while a single simulation is running", async () => {
    mockIsRunning = true;
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "merged: yaml\nextra: 1\n" } });

    expect(saveButton()).toBeDisabled();
  });

  it("Ctrl+S does not save while a calculation is running", async () => {
    mockSweeping = true;
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "merged: yaml\nextra: 1\n" } });

    fireEvent.keyDown(window, { key: "s", ctrlKey: true });
    expect(mockParseYaml).not.toHaveBeenCalled();
  });

  it("mounts an empty, editable pane instead of an error when nothing is loaded yet", async () => {
    mockConfig = { nodes: [], connections: [] };
    mockOriginalYaml = "";
    render(<YamlPane />);

    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue(""));
    expect(screen.queryByText("No configuration available to edit.")).not.toBeInTheDocument();

    fireEvent.change(editor, { target: { value: "nodes: []\n" } });
    expect(editor).toHaveValue("nodes: []\n");
    expect(saveButton()).not.toBeDisabled();
  });

  it("still shows the error when there's a live graph but no YAML to merge it into", async () => {
    mockConfig = {
      nodes: [{ id: "r1", type: "IdealGasReactor", properties: {} }],
      connections: [],
    };
    mockOriginalYaml = "";
    render(<YamlPane />);

    expect(await screen.findByText("No configuration available to edit.")).toBeInTheDocument();
    expect(mockSyncConfig).not.toHaveBeenCalled();
  });

  it("closes immediately when there are no unsaved edits", async () => {
    render(<YamlPane />);
    await editorValue();
    fireEvent.click(screen.getByRole("button", { name: "Close YAML pane" }));
    expect(mockCloseYamlPane).toHaveBeenCalledOnce();
  });

  it("confirms before closing with unsaved edits, and respects Cancel on the confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "scratch\n" } });

    fireEvent.click(screen.getByRole("button", { name: "Close YAML pane" }));
    expect(confirmSpy).toHaveBeenCalledOnce();
    expect(mockCloseYamlPane).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Close YAML pane" }));
    expect(mockCloseYamlPane).toHaveBeenCalledOnce();
    confirmSpy.mockRestore();
  });

  it("refreshes the displayed YAML when the config changes elsewhere and nothing is unsaved", async () => {
    const { rerender } = render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    expect(mockSyncConfig).toHaveBeenCalledOnce();

    mockConfig = { nodes: [{ id: "r2", type: "Reservoir", properties: {} }], connections: [] };
    mockSyncConfig.mockResolvedValue({ yaml: "merged: yaml\nnew: node\n", warnings: [] });
    rerender(<YamlPane />);

    await waitFor(() => expect(mockSyncConfig).toHaveBeenCalledTimes(2));
    // Re-query rather than reusing `editor`: assert on the live DOM, not a
    // reference that may be stale if anything upstream ever re-mounts it.
    await waitFor(() =>
      expect(screen.getByTestId("monaco-stub")).toHaveValue("merged: yaml\nnew: node\n"),
    );
  });

  it("does not clobber an unsaved edit when the config changes elsewhere", async () => {
    const { rerender } = render(<YamlPane />);
    const editor = await editorValue();
    await waitFor(() => expect(editor).toHaveValue("merged: yaml\n"));
    fireEvent.change(editor, { target: { value: "my in-progress edit\n" } });

    mockConfig = { nodes: [{ id: "r2", type: "Reservoir", properties: {} }], connections: [] };
    rerender(<YamlPane />);

    // Give any (unwanted) refresh a chance to run before asserting it didn't.
    await new Promise((r) => setTimeout(r, 0));
    expect(mockSyncConfig).toHaveBeenCalledOnce();
    expect(editor).toHaveValue("my in-progress edit\n");
  });
});
