/**
 * Asserts SweepCalculatingCard: shows the scenario id and a stage label when
 * there's more than one stage, and omits the stage label when there's only
 * one (or stage data hasn't arrived yet) — a single-stage network shouldn't
 * say "Stage 1/1".
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SweepCalculatingCard } from "./SweepCalculatingCard";

describe("SweepCalculatingCard", () => {
  it("shows the scenario id and a stage label for a multi-stage network", () => {
    render(
      <SweepCalculatingCard
        scenarioId="cold_feed"
        stage={{ stage: 1, stageTotal: 3 }}
      />,
    );

    expect(screen.getByText(/Calculating "cold_feed"…/)).toBeInTheDocument();
    expect(screen.getByText(/Stage 1\/3/)).toBeInTheDocument();
  });

  it("omits the stage label for a single-stage network", () => {
    render(
      <SweepCalculatingCard
        scenarioId="cold_feed"
        stage={{ stage: 1, stageTotal: 1 }}
      />,
    );

    expect(screen.getByText(/Calculating "cold_feed"…/)).toBeInTheDocument();
    expect(screen.queryByText(/Stage/)).not.toBeInTheDocument();
  });

  it("omits the stage label when no stage data has arrived yet", () => {
    render(<SweepCalculatingCard scenarioId="cold_feed" stage={undefined} />);

    expect(screen.getByText(/Calculating "cold_feed"…/)).toBeInTheDocument();
    expect(screen.queryByText(/Stage/)).not.toBeInTheDocument();
  });
});
