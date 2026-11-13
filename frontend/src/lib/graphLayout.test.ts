/**
 * Vitest unit tests for inferLanesFromTopology on cyclic networks.
 *
 * Asserts:
 * - A cyclic network (an exchange pair, a node declared before every node
 *   that feeds it) returns lanes instead of looping forever.
 * - So does a cyclic grid declared from the outlet back to the inlet.
 * - On an acyclic chain, the whole chain (minus the feed) is the spine.
 * - metadata.layout_position is read only when both coordinates are finite.
 */

import cytoscape from "cytoscape";
import { describe, expect, it } from "vitest";
import { inferLanesFromTopology, LAYOUT_LANE_MAIN, layoutPosition } from "./graphLayout";

type Conn = { id: string; source: string; target: string };

function graph(nodes: { id: string; type: string }[], conns: Conn[]) {
  const cy = cytoscape({
    headless: true,
    elements: [
      ...nodes.map((n) => ({ data: { id: n.id, type: n.type } })),
      ...conns.map((c) => ({ data: { id: c.id, source: c.source, target: c.target } })),
    ],
  });
  return inferLanesFromTopology(cy, nodes, conns, new Set());
}

describe("inferLanesFromTopology", () => {
  it("terminates when a node is declared before every node feeding it", () => {
    // `x` is declared first but only `y` feeds it, and `x` <-> `y` exchange
    // mass: Kahn's sort stalls on the cycle, and a longest-path pass that
    // follows back edges makes x and y each other's predecessor.
    const nodes = [
      { id: "feed", type: "Reservoir" },
      { id: "x", type: "IdealGasReactor" },
      { id: "y", type: "IdealGasReactor" },
      { id: "exhaust", type: "OutletSink" },
    ];
    const conns: Conn[] = [
      { id: "feed_y", source: "feed", target: "y" },
      { id: "y_x", source: "y", target: "x" },
      { id: "x_y", source: "x", target: "y" },
      { id: "x_exhaust", source: "x", target: "exhaust" },
    ];
    const { lanes } = graph(nodes, conns);

    expect(lanes.size).toBe(nodes.length);
    expect(lanes.get("feed")).toBe("auto_branch");
    expect([...lanes.values()]).toContain(LAYOUT_LANE_MAIN);
  });

  it("terminates on a cyclic grid declared downstream-first", () => {
    // A generated network in arbitrary order: forward flow, a recirculation
    // per row and exchange pairs between neighbours, reactors listed from
    // the outlet back to the inlet.
    const nx = 6;
    const ny = 4;
    const r = (i: number, j: number) => `r_${i}_${j}`;
    const nodes = [{ id: "feed", type: "Reservoir" }, { id: "exhaust", type: "OutletSink" }];
    const conns: Conn[] = [];
    for (let i = nx - 1; i >= 0; i--) {
      for (let j = ny - 1; j >= 0; j--) nodes.push({ id: r(i, j), type: "IdealGasReactor" });
    }
    const link = (a: string, b: string) => conns.push({ id: `${a}>${b}`, source: a, target: b });
    for (let j = 0; j < ny; j++) {
      link("feed", r(0, j));
      for (let i = 0; i < nx - 1; i++) link(r(i, j), r(i + 1, j));
      link(r(nx - 1, j), r(0, j));
      link(r(nx - 1, j), "exhaust");
      for (let i = 0; i < nx; i++) {
        if (j + 1 < ny) {
          link(r(i, j), r(i, j + 1));
          link(r(i, j + 1), r(i, j));
        }
        if (i + 1 < nx) link(r(i + 1, j), r(i, j));
      }
    }
    const { lanes } = graph(nodes, conns);

    expect(lanes.size).toBe(nodes.length);
  });

  it("puts an acyclic chain on the spine", () => {
    const nodes = [
      { id: "feed", type: "Reservoir" },
      { id: "a", type: "IdealGasReactor" },
      { id: "b", type: "IdealGasReactor" },
      { id: "exhaust", type: "OutletSink" },
    ];
    const conns: Conn[] = [
      { id: "feed_a", source: "feed", target: "a" },
      { id: "a_b", source: "a", target: "b" },
      { id: "b_exhaust", source: "b", target: "exhaust" },
    ];
    const { lanes } = graph(nodes, conns);

    expect(lanes.get("a")).toBe(LAYOUT_LANE_MAIN);
    expect(lanes.get("b")).toBe(LAYOUT_LANE_MAIN);
    expect(lanes.get("exhaust")).toBe(LAYOUT_LANE_MAIN);
    expect(lanes.get("feed")).toBe("auto_branch");
  });

  it("reads metadata.layout_position only when x and y are finite numbers", () => {
    expect(layoutPosition({ layout_position: { x: 10, y: -5 } })).toEqual({ x: 10, y: -5 });
    expect(layoutPosition({ layout_position: { x: "10", y: 5 } })).toBeNull();
    expect(layoutPosition({ layout_position: { x: Infinity, y: 5 } })).toBeNull();
    expect(layoutPosition(null)).toBeNull();
  });
});
