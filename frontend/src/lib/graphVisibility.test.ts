/**
 * A `skip_viz` reactor must survive the post-run topology sync.
 *
 * Regression: a design reactor whose unfolder adds a wall satellite is flagged
 * `skip_viz`. It rendered during the build, then vanished once results landed,
 * because the solver's `<id>_outlet` StreamConnector matched the child-prefix
 * heuristic — the graph showed the upstream stage feeding the downstream
 * stage directly, with the reactor itself gone.
 */
import { describe, expect, it } from "vitest";

import { hiddenCompositeNodeIds } from "./graphVisibility";

const skip = { skip_viz: true };

describe("hiddenCompositeNodeIds", () => {
  it("hides a composite parent wired to its children by mass flow", () => {
    const nodes = [{ id: "cgr", metadata: skip }, { id: "cgr_seg1" }];
    const conns = [{ source: "cgr", target: "cgr_seg1", type: "MassFlowController" }];
    expect(hiddenCompositeNodeIds(nodes, conns)).toEqual(new Set(["cgr"]));
  });

  it("ignores nodes without skip_viz", () => {
    const nodes = [{ id: "cgr" }, { id: "cgr_seg1" }];
    const conns = [{ source: "cgr", target: "cgr_seg1", type: "MassFlowController" }];
    expect(hiddenCompositeNodeIds(nodes, conns).size).toBe(0);
  });

  it("does not count a Wall to a same-group satellite", () => {
    const nodes = [{ id: "pfr", metadata: skip }, { id: "pfr_ambient" }];
    const conns = [{ source: "pfr", target: "pfr_ambient", type: "Wall" }];
    expect(hiddenCompositeNodeIds(nodes, conns).size).toBe(0);
  });

  it("does not count the solver's stream-point plumbing after a run", () => {
    const nodes = [
      { id: "reactor", metadata: skip },
      { id: "reactor_wall_reservoir" },
      { id: "reactor_outlet", metadata: { stream_point: true } },
    ];
    const conns = [
      { source: "reactor_wall_reservoir", target: "reactor", type: "Wall" },
      {
        source: "reactor",
        target: "reactor_outlet",
        type: "StreamConnector",
        metadata: { stream_point: true, side: "outlet_connector" },
      },
      {
        source: "reactor_outlet",
        target: "sink",
        type: "MassFlowController",
        metadata: { stream_point: true, side: "inlet" },
      },
    ];
    expect(hiddenCompositeNodeIds(nodes, conns).size).toBe(0);
  });
});
