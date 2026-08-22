/**
 * Asserts NetworkCard: shows the current filename and calls onEditYaml when
 * "Edit YAML" is clicked, rather than relying on the filename itself being
 * clickable (that affordance wasn't discoverable). Also asserts the
 * scenario-aware "Edit YAML" behavior: it edits the full base config when
 * no scenario (or BASELINE, the base config's own unmodified run) is
 * active, and only that scenario's overlay subtree otherwise.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { NetworkCard } from "./NetworkCard";

let mockFileName: string | null = "SPRING_A4_C1X_20260326.yaml";
let mockActiveId: string | null = null;

const mockSetConfig = vi.fn();
vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({ setConfig: mockSetConfig, fileName: mockFileName }),
}));

const mockResetForNewConfig = vi.fn();
vi.mock("@/stores/scenarioStore", () => {
  const useScenarioStore = (selector: (s: { activeId: string | null }) => unknown) =>
    selector({ activeId: mockActiveId });
  (useScenarioStore as unknown as { getState: () => unknown }).getState = () => ({
    resetForNewConfig: mockResetForNewConfig,
  });
  return { useScenarioStore };
});

const mockOpenScenarioYamlEditor = vi.fn();
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: unknown) => unknown) =>
    selector({ openScenarioYamlEditor: mockOpenScenarioYamlEditor }),
}));

const mockUploadConfigFile = vi.fn();
vi.mock("@/api/configs", () => ({
  uploadConfigFile: (...args: unknown[]) => mockUploadConfigFile(...args),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("NetworkCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFileName = "SPRING_A4_C1X_20260326.yaml";
    mockActiveId = null;
  });

  it("shows the current filename", () => {
    render(<NetworkCard onEditYaml={vi.fn()} />);
    expect(screen.getByText("SPRING_A4_C1X_20260326.yaml")).toBeInTheDocument();
  });

  it("falls back to a placeholder filename when none is loaded", () => {
    mockFileName = null;
    render(<NetworkCard onEditYaml={vi.fn()} />);
    expect(screen.getByText("untitled.yaml")).toBeInTheDocument();
  });

  it("calls onEditYaml when Edit YAML is clicked with no scenario active", () => {
    const onEditYaml = vi.fn();
    render(<NetworkCard onEditYaml={onEditYaml} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit YAML" }));
    expect(onEditYaml).toHaveBeenCalledOnce();
    expect(mockOpenScenarioYamlEditor).not.toHaveBeenCalled();
  });

  it("calls onEditYaml (not the scenario editor) when BASELINE is active", () => {
    mockActiveId = "BASELINE";
    const onEditYaml = vi.fn();
    render(<NetworkCard onEditYaml={onEditYaml} />);
    expect(screen.getByRole("button", { name: "Edit YAML" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit YAML" }));
    expect(onEditYaml).toHaveBeenCalledOnce();
    expect(mockOpenScenarioYamlEditor).not.toHaveBeenCalled();
  });

  it("labels the button with the active scenario and edits its overlay only", () => {
    mockActiveId = "C1T";
    const onEditYaml = vi.fn();
    render(<NetworkCard onEditYaml={onEditYaml} />);
    const btn = screen.getByRole("button", { name: "Edit YAML (C1T)" });
    fireEvent.click(btn);
    expect(mockOpenScenarioYamlEditor).toHaveBeenCalledWith("C1T");
    expect(onEditYaml).not.toHaveBeenCalled();
  });

  it("resets the scenario store to the new config's own scenarios after an upload", async () => {
    mockUploadConfigFile.mockResolvedValue({
      config: { nodes: [], connections: [] },
      filename: "uploaded.yaml",
      yaml: "nodes: []\n",
    });
    render(<NetworkCard onEditYaml={vi.fn()} />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["nodes: []\n"], "uploaded.yaml", { type: "application/x-yaml" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockSetConfig).toHaveBeenCalledOnce());
    expect(mockResetForNewConfig).toHaveBeenCalledOnce();
  });
});
