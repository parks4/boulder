/**
 * Who the results pane follows during a sweep.
 *
 * By default the solver: the "Calculating …" card must appear without the user
 * clicking anything, and move on with the sweep. A mid-sweep selection pins it
 * instead — the user has taken the wheel — and selecting the scenario that is
 * itself solving hands control back.
 *
 * Regression: the pane used to key off the *selected* scenario alone. Nothing
 * is selected when a sweep starts, so no card ever appeared unless you happened
 * to click the scenario being solved right then.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { useScenarioStore } from "./scenarioStore";
import { useSweepRunStore } from "./sweepStore";

/** The gate `ResultsTabs` applies, kept in step with it. */
function followedId(
  pinnedId: string | null,
  scenarioProgress: Record<string, unknown>,
): string | null {
  const solvingId = Object.keys(scenarioProgress).at(-1) ?? null;
  const followed = pinnedId ?? solvingId;
  return followed != null && followed in scenarioProgress ? followed : null;
}

describe("sweep follow", () => {
  beforeEach(() => {
    useSweepRunStore.setState({ sweeping: false, pinnedId: null, scenarioProgress: {} });
    useScenarioStore.setState({ activeId: null, scenarios: [] });
  });

  it("follows the solving scenario when the user has not chosen one", () => {
    expect(followedId(null, { hot: { stage: 1 } })).toBe("hot");
  });

  it("moves on with the sweep", () => {
    expect(followedId(null, { hot: { stage: 3 } })).toBe("hot");
    expect(followedId(null, { cold: { stage: 1 } })).toBe("cold");
  });

  it("stops following once the user selects another scenario mid-sweep", async () => {
    useSweepRunStore.setState({ sweeping: true });
    await useScenarioStore.getState().setActive("already_done");

    const pinned = useSweepRunStore.getState().pinnedId;
    expect(pinned).toBe("already_done");
    // Not in progress -> no card, so the pane shows that scenario's results.
    expect(followedId(pinned, { hot: { stage: 2 } })).toBeNull();
  });

  it("resumes following when the user selects the scenario being solved", async () => {
    useSweepRunStore.setState({ sweeping: true });
    await useScenarioStore.getState().setActive("hot");

    expect(followedId(useSweepRunStore.getState().pinnedId, { hot: { stage: 2 } })).toBe("hot");
  });

  it("does not pin a selection made outside a sweep", async () => {
    useSweepRunStore.setState({ sweeping: false });
    await useScenarioStore.getState().setActive("whatever");

    expect(useSweepRunStore.getState().pinnedId).toBeNull();
  });
});
