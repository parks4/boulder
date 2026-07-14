/**
 * Asserts PaneToggle: nudges toward Ctrl+B after repeatedly clicking the
 * left-sidebar toggle by mouse, and never nudges the right-sidebar toggle
 * (it has no keyboard shortcut).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { PaneToggle } from "./paneControls";

const mockToastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: { info: (...args: unknown[]) => mockToastInfo(...args) },
}));

const mockToggleLeft = vi.fn();
const mockToggleRight = vi.fn();
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: () => ({
    leftCollapsed: false,
    rightCollapsed: false,
    toggleLeft: mockToggleLeft,
    toggleRight: mockToggleRight,
  }),
}));

describe("PaneToggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("nudges toward Ctrl+B after repeatedly clicking the left toggle by mouse", () => {
    render(<PaneToggle side="left" />);
    const button = screen.getByLabelText("Collapse left sidebar");
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mockToastInfo).not.toHaveBeenCalled();

    fireEvent.click(button);
    expect(mockToastInfo).toHaveBeenCalledOnce();
    expect(mockToastInfo).toHaveBeenCalledWith(expect.stringContaining("Ctrl+B"));
  });

  it("never nudges the right toggle, since it has no keyboard shortcut", () => {
    render(<PaneToggle side="right" />);
    const button = screen.getByLabelText("Collapse right sidebar");
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    expect(mockToastInfo).not.toHaveBeenCalled();
  });
});
