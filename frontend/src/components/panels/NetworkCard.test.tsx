/**
 * Asserts NetworkCard: shows the current filename and calls onEditYaml when
 * "Edit YAML" is clicked, rather than relying on the filename itself being
 * clickable (that affordance wasn't discoverable).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { NetworkCard } from "./NetworkCard";

let mockFileName: string | null = "SPRING_A4_C1X_20260326.yaml";

vi.mock("@/stores/configStore", () => ({
  useConfigStore: (selector: (s: unknown) => unknown) =>
    selector({ setConfig: vi.fn(), fileName: mockFileName }),
}));

vi.mock("@/api/configs", () => ({
  uploadConfigFile: vi.fn(),
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
});
