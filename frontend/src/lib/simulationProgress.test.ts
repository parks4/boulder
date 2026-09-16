/**
 * Which stage box lights up while solving.
 *
 * One rule shared by a plain run, a selected scenario and each sweep entry:
 * the first stage in declaration order not yet reported complete. A plain
 * run used to get no tint at all because only the sweep path derived this.
 */
import { describe, expect, it } from "vitest";

import { currentStageId } from "./simulationProgress";

const groups = { stage_a: {}, stage_b: {}, stage_c: {} };

describe("currentStageId", () => {
  it("starts with the first stage when nothing is done", () => {
    expect(currentStageId(groups, [])).toBe("stage_a");
    expect(currentStageId(groups, undefined)).toBe("stage_a");
  });

  it("advances in declaration order as stages complete", () => {
    expect(currentStageId(groups, ["stage_a"])).toBe("stage_b");
    expect(currentStageId(groups, ["stage_a", "stage_b"])).toBe("stage_c");
  });

  it("is null once every stage is done, or without groups", () => {
    expect(currentStageId(groups, ["stage_a", "stage_b", "stage_c"])).toBeNull();
    expect(currentStageId(undefined, [])).toBeNull();
  });

  it("lights the single synthesized box of a one-stage config", () => {
    expect(currentStageId({ default: {} }, [])).toBe("default");
  });
});
