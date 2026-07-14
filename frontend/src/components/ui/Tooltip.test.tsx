/**
 * Asserts the Tooltip shows its content on hover/focus, including when the
 * wrapped trigger is a disabled button (whose own `title` never fires
 * because `disabled:pointer-events-none` blocks hover on the button itself).
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Tooltip } from "./Tooltip";
import { Button } from "./Button";

describe("Tooltip", () => {
  it("is hidden until hovered", () => {
    render(
      <Tooltip content="Explanation">
        <button>Trigger</button>
      </Tooltip>,
    );
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows and hides its content on mouse enter/leave", () => {
    render(
      <Tooltip content="Explanation">
        <button>Trigger</button>
      </Tooltip>,
    );
    const wrapper = screen.getByText("Trigger").closest("span")?.parentElement;
    if (!wrapper) throw new Error("wrapper span not found");

    fireEvent.mouseEnter(wrapper);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Explanation");

    fireEvent.mouseLeave(wrapper);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("still shows on hover when the wrapped button is disabled", () => {
    render(
      <Tooltip content="Add at least 2 reactors first">
        <Button disabled>+ Add Connection</Button>
      </Tooltip>,
    );
    const wrapper = screen.getByText("+ Add Connection").closest("button")
      ?.parentElement;
    if (!wrapper) throw new Error("wrapper span not found");

    fireEvent.mouseEnter(wrapper);
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Add at least 2 reactors first",
    );
  });
});
