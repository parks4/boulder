/**
 * Asserts NetworkCard: shows the current filename and calls onEditYaml when
 * "Edit YAML" is clicked, rather than relying on the filename itself being
 * clickable (that affordance wasn't discoverable).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { NetworkCard } from "./NetworkCard";

let mockFileName: string | null = "SPRING_A4_C1X_20260326.yaml";

const mockSetConfig = vi.fn();
vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({ setConfig: mockSetConfig, fileName: mockFileName }),
}));

const mockScenarioRefresh = vi.fn();
vi.mock("@/stores/scenarioStore", () => ({
  useScenarioStore: { getState: () => ({ refresh: mockScenarioRefresh }) },
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

  it("calls onEditYaml when Edit YAML is clicked", () => {
    const onEditYaml = vi.fn();
    render(<NetworkCard onEditYaml={onEditYaml} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit YAML" }));
    expect(onEditYaml).toHaveBeenCalledOnce();
  });

  it("nudges RunControl to re-check Run Sweep availability after an upload", async () => {
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
    expect(mockScenarioRefresh).toHaveBeenCalledOnce();
  });
});
