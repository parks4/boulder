/**
 * Asserts ScenarioYamlPane: fetches one scenario's overlay text on open,
 * saves via updateScenario (not the base config's sync path), and refetches
 * when scenarioStore.revision bumps (a write made elsewhere, e.g. the
 * Properties panel, while this pane sits open on the same scenario) --
 * unless there's an unsaved edit sitting in the editor, mirroring YamlPane's
 * own dirty-guard for the base config.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ScenarioYamlPane } from "./ScenarioYamlPane";

vi.mock("@monaco-editor/react", () => ({
  default: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea data-testid="monaco-stub" value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

const mockFetchScenarioSource = vi.fn();
const mockUpdateScenario = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/scenarios", () => ({
  fetchScenarioSource: (...args: unknown[]) => mockFetchScenarioSource(...args),
  updateScenario: (...args: unknown[]) => mockUpdateScenario(...args),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: unknown) => unknown) => selector({ theme: "light" }),
}));

let mockRevision = 0;
vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: (selector: (s: unknown) => unknown) => selector({ revision: mockRevision }),
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

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

async function editorValue() {
  return (await screen.findByTestId("monaco-stub")) as HTMLTextAreaElement;
}

describe("ScenarioYamlPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRevision = 0;
    mockIsRunning = false;
    mockSweeping = false;
    mockFetchScenarioSource.mockResolvedValue({ scenario_id: "C1T", yaml: "torch_eff: 0.85\n" });
    mockUpdateScenario.mockResolvedValue(undefined);
  });

  it("fetches the scenario's overlay text when opened", async () => {
    render(<ScenarioYamlPane scenarioId="C1T" onClose={vi.fn()} />);

    expect(mockFetchScenarioSource).toHaveBeenCalledWith("C1T");
    expect(await editorValue()).toHaveValue("torch_eff: 0.85\n");
  });

  it("refetches when revision bumps while the pane is clean (unedited)", async () => {
    render(<ScenarioYamlPane scenarioId="C1T" onClose={vi.fn()} />);
    await editorValue();
    expect(mockFetchScenarioSource).toHaveBeenCalledTimes(1);

    mockFetchScenarioSource.mockResolvedValue({
      scenario_id: "C1T",
      yaml: "torch_eff: 0.95\n",
    });
    mockRevision = 1;
    render(<ScenarioYamlPane scenarioId="C1T" onClose={vi.fn()} />);

    await waitFor(() => expect(mockFetchScenarioSource).toHaveBeenCalledTimes(2));
  });

  it("does not clobber an unsaved edit when revision bumps", async () => {
    const { rerender } = render(<ScenarioYamlPane scenarioId="C1T" onClose={vi.fn()} />);
    const editor = await editorValue();
    fireEvent.change(editor, { target: { value: "torch_eff: 0.5  # unsaved\n" } });

    mockRevision = 1;
    rerender(<ScenarioYamlPane scenarioId="C1T" onClose={vi.fn()} />);

    // Only the initial mount fetch -- the bump while dirty must not refetch
    // and silently discard the unsaved edit.
    expect(mockFetchScenarioSource).toHaveBeenCalledTimes(1);
    expect(editor).toHaveValue("torch_eff: 0.5  # unsaved\n");
  });

  it("saves via updateScenario, not the base config's YAML sync", async () => {
    const onSaved = vi.fn();
    render(<ScenarioYamlPane scenarioId="C1T" onClose={vi.fn()} onSaved={onSaved} />);
    const editor = await editorValue();
    fireEvent.change(editor, { target: { value: "torch_eff: 0.99\n" } });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mockUpdateScenario).toHaveBeenCalledWith("C1T", "torch_eff: 0.99\n"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("C1T"));
  });

  it("locks editing while a calculation is running", async () => {
    mockSweeping = true;
    render(<ScenarioYamlPane scenarioId="C1T" onClose={vi.fn()} />);
    await editorValue();

    expect(screen.getByText(/locked until it finishes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
