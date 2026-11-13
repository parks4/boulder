import type { Core } from "cytoscape";

/** Swim lane of the horizontal main-flow baseline. */
export const LAYOUT_LANE_MAIN = "main_flow";

// Above this many nodes + connections the graph switches to a cheap style:
// straight unlabelled edges with small arrows, node labels hidden when zoomed
// out (frontend/SPECIFICATIONS.md GRAPH-07).
export const LARGE_GRAPH_ELEMENTS = 1000;

/** ``metadata.layout_position`` ({x, y}, canvas units, y down) when valid. */
export function layoutPosition(
  metadata: Record<string, unknown> | null | undefined,
): { x: number; y: number } | null {
  const p = metadata?.layout_position as { x?: unknown; y?: unknown } | undefined;
  if (!p || typeof p.x !== "number" || typeof p.y !== "number") return null;
  if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) return null;
  return { x: p.x, y: p.y };
}

type LaneNode = { id: string };
type LaneConnection = { source: string; target: string };

/**
 * Infer swim-lane assignments from network topology when no explicit
 * layout_lane metadata is present in the config.
 *
 * Algorithm:
 *   1. Build a DAG over all rendered non-group, non-stream-point nodes using
 *      connections (same _outlet alias collapsing as alignLayoutLanes).
 *   2. Find the longest source-to-sink path (DP on topo order).  Tie-break:
 *      prefer reactor-type nodes (non-Reservoir / non-OutletSink) over boundary
 *      nodes; then stable declaration order.  Feed Reservoirs on that path are
 *      demoted to branches so parallel inlets (e.g. air + fuel → mixer) do not
 *      share the horizontal spine.
 *   3. All other nodes are "auto_branch".  Each branch node is anchored to its
 *      closest spine neighbor: prefer the spine node it connects INTO; fall back
 *      to the spine node that connects INTO it.
 *
 * Stream-point diamonds and group compound nodes are excluded — they are handled
 * separately by Steps 3.6 and 5 of alignLayoutLanes.
 *
 * Returns { lanes: Map<id,lane>, anchors: Map<branchId, spineId> }.
 * Both maps are empty if the graph has no nodes.
 */
export function inferLanesFromTopology(
  cy: Core,
  nodes: LaneNode[],
  connections: LaneConnection[],
  hiddenIds: Set<string>,
): { lanes: Map<string, string>; anchors: Map<string, string> } {
  const empty = { lanes: new Map<string, string>(), anchors: new Map<string, string>() };

  // Collect candidate nodes: leaf, non-group, non-stream-point.
  const candidateIds = new Set<string>();
  cy.nodes().forEach((n) => {
    if (n.data("isGroup") || n.data("stream_point")) return;
    candidateIds.add(n.id());
  });
  if (candidateIds.size === 0) return empty;

  // Truly hidden (composite placeholder) node ids: used to short-circuit
  // topology traversal so that predecessors connect directly to successors,
  // making hidden unfolded composites transparent to layout inference.
  const skipVizIds = hiddenIds;

  // Build adjacency lists over candidate nodes.
  // Collapse "_outlet" source aliases to the base node id.
  // Connections passing through skip_viz nodes are short-circuited:
  //   A → [hidden] → B  becomes  A → B.
  const outEdges = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const id of candidateIds) {
    outEdges.set(id, []);
    inDegree.set(id, 0);
  }
  const addEdge = (rawSrc: string, tgt: string) => {
    const src = rawSrc.endsWith("_outlet") ? rawSrc.slice(0, -"_outlet".length) : rawSrc;
    if (!candidateIds.has(src) || !candidateIds.has(tgt) || src === tgt) return;
    // Avoid duplicate edges.
    if (!outEdges.get(src)!.includes(tgt)) {
      outEdges.get(src)!.push(tgt);
      inDegree.set(tgt, (inDegree.get(tgt) ?? 0) + 1);
    }
  };

  // Build a raw adjacency map over ALL connections (including those
  // involving hidden nodes) so we can resolve transitive paths.
  const rawOut = new Map<string, string[]>();
  for (const conn of connections) {
    const src = conn.source.endsWith("_outlet")
      ? conn.source.slice(0, -"_outlet".length)
      : conn.source;
    if (!rawOut.has(src)) rawOut.set(src, []);
    rawOut.get(src)!.push(conn.target);
  }

  // Helper: walk forward from `start` through skip_viz nodes and collect
  // all reachable non-skip_viz nodes (i.e. candidate nodes).
  const resolveSuccessors = (start: string): string[] => {
    const visited = new Set<string>();
    const result: string[] = [];
    const stack = [start];
    while (stack.length > 0) {
      const cur = stack.pop()!;
      if (visited.has(cur)) continue;
      visited.add(cur);
      for (const nb of rawOut.get(cur) ?? []) {
        if (candidateIds.has(nb)) {
          result.push(nb);
        } else if (skipVizIds.has(nb)) {
          stack.push(nb);
        }
      }
    }
    return result;
  };

  for (const conn of connections) {
    const srcRaw = conn.source.endsWith("_outlet")
      ? conn.source.slice(0, -"_outlet".length)
      : conn.source;
    const tgtRaw = conn.target;
    if (candidateIds.has(srcRaw)) {
      if (candidateIds.has(tgtRaw)) {
        addEdge(srcRaw, tgtRaw);
      } else if (skipVizIds.has(tgtRaw)) {
        // Short-circuit: connect srcRaw directly to all visible successors
        // reachable through hidden nodes.
        for (const succ of resolveSuccessors(tgtRaw)) {
          addEdge(srcRaw, succ);
        }
      }
    }
  }
  cy.edges().forEach((e) => {
    addEdge(e.source().id(), e.target().id());
  });

  // Kahn's topological sort over candidate nodes.
  const topoOrder: string[] = [];
  const tempDeg = new Map(inDegree);
  const queue: string[] = [];
  for (const id of candidateIds) {
    if ((tempDeg.get(id) ?? 0) === 0) queue.push(id);
  }
  // Stable initial ordering by declaration order in nodes.
  const declOrder = new Map<string, number>();
  nodes.forEach((n, i) => declOrder.set(n.id, i));
  queue.sort((a, b) => (declOrder.get(a) ?? 999) - (declOrder.get(b) ?? 999));
  while (queue.length > 0) {
    const cur = queue.shift()!;
    topoOrder.push(cur);
    const next: string[] = [];
    for (const nb of outEdges.get(cur) ?? []) {
      const deg = (tempDeg.get(nb) ?? 0) - 1;
      tempDeg.set(nb, deg);
      if (deg === 0) next.push(nb);
    }
    next.sort((a, b) => (declOrder.get(a) ?? 999) - (declOrder.get(b) ?? 999));
    queue.push(...next);
  }
  // Append any remaining (cycle remnants) in declaration order.
  const sorted = new Set(topoOrder);
  for (const id of candidateIds) {
    if (!sorted.has(id)) topoOrder.push(id);
  }

  // Determine node "spine weight": reactor-type and sink nodes score 1
  // (preferred on the main spine); pure feed nodes (Reservoir) score 0 so
  // that feed branches don't drag the spine out of its natural direction.
  // OutletSink is the terminal main-flow node — weight 1 ensures the spine
  // always extends all the way to the outlet.
  const spineWeight = (id: string): number => {
    const t = cy.getElementById(id).data("type") as string | undefined;
    if (!t || t === "Reservoir") return 0;
    return 1;
  };

  // DP: longest weighted path ending at each node.
  // pathLen[n] = max over predecessors p of (pathLen[p] + spineWeight(n)).
  // Only predecessors earlier in topoOrder count: on a cyclic network (cycle
  // remnants above) a back edge would let two nodes become each other's
  // pathPrev and the spine trace-back below would never end.
  const preds = new Map<string, string[]>();
  for (const id of topoOrder) {
    for (const nb of outEdges.get(id) ?? []) {
      if (!preds.has(nb)) preds.set(nb, []);
      preds.get(nb)!.push(id);
    }
  }
  const pathLen = new Map<string, number>();
  const pathPrev = new Map<string, string | null>();
  for (const id of topoOrder) {
    let best = 0;
    let bestPrev: string | null = null;
    for (const pred of preds.get(id) ?? []) {
      if (pathLen.has(pred)) {
        const val = pathLen.get(pred)! + spineWeight(id);
        if (val > best || (val === best && bestPrev === null)) {
          best = val;
          bestPrev = pred;
        }
      }
    }
    pathLen.set(id, best + spineWeight(id));
    pathPrev.set(id, bestPrev);
  }

  // Find the sink with the longest path (tie-break: prefer spine weight, then
  // declaration order).
  let bestSink: string | null = null;
  let bestLen = -1;
  for (const id of topoOrder) {
    const len = pathLen.get(id) ?? 0;
    const w = spineWeight(id);
    const decl = declOrder.get(id) ?? 999;
    if (
      bestSink === null ||
      len > bestLen ||
      (len === bestLen && w > spineWeight(bestSink)) ||
      (len === bestLen && w === spineWeight(bestSink) && decl < (declOrder.get(bestSink) ?? 999))
    ) {
      bestSink = id;
      bestLen = len;
    }
  }
  if (bestSink === null) return empty;

  // Trace back the spine path from bestSink.
  const spineSet = new Set<string>();
  let cur: string | null = bestSink;
  while (cur !== null) {
    spineSet.add(cur);
    cur = pathPrev.get(cur) ?? null;
  }

  // Assign lanes.  Feed reservoirs never sit on the main-flow spine even when
  // they appear on the longest path (parallel MFC inlets anchor as branches).
  const lanes = new Map<string, string>();
  for (const id of candidateIds) {
    const t = cy.getElementById(id).data("type") as string | undefined;
    const onSpine = spineSet.has(id) && t !== "Reservoir";
    lanes.set(id, onSpine ? LAYOUT_LANE_MAIN : "auto_branch");
  }

  // Assign anchors: for each branch node, find the closest spine neighbor.
  // Priority: a spine node this branch feeds INTO (downstream); else a spine
  // node that feeds INTO this branch (upstream).
  const anchors = new Map<string, string>();
  for (const id of candidateIds) {
    if (spineSet.has(id)) continue;
    // Downstream spine neighbors (id → spine).
    for (const nb of outEdges.get(id) ?? []) {
      if (spineSet.has(nb) && !anchors.has(id)) {
        anchors.set(id, nb);
      }
    }
    if (anchors.has(id)) continue;
    // Upstream spine neighbors (spine → id).
    for (const pred of candidateIds) {
      if (spineSet.has(pred) && (outEdges.get(pred) ?? []).includes(id)) {
        anchors.set(id, pred);
        break;
      }
    }
    // Last resort: any spine node.
    if (!anchors.has(id) && spineSet.size > 0) {
      anchors.set(id, [...spineSet][0]);
    }
  }

  return { lanes, anchors };
}
