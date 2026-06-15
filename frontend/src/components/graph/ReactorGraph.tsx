import { useEffect, useRef, useCallback, useState, useMemo } from "react";
import cytoscape, { type Core, type EventObject } from "cytoscape";
// @ts-ignore - no types available
import dagre from "cytoscape-dagre";
import { useConfigStore } from "@/stores/configStore";
import { useSelectionStore } from "@/stores/selectionStore";
import { useResultsTabStore } from "@/stores/resultsTabStore";
import { useThemeStore } from "@/stores/themeStore";

// Register dagre layout
cytoscape.use(dagre);

/**
 * Native Cytoscape.js graph component for the reactor network.
 * Uses dagre left-to-right layout with stages ordered top-to-bottom.
 */
const DBLTAP_MS = 300;
const DEFAULT_GRAPH_HEIGHT = 360;
const MIN_GRAPH_HEIGHT = 240;
const GRAPH_HEIGHT_STORAGE_KEY = "boulder-graph-height";

// Lane layout constants — used by alignLayoutLanes.
// "main_flow" is the horizontal baseline; all other lanes are placed at a
// Y offset defined in each node's metadata.layout_y_offset (negative = above
// in screen space after flipLayoutVertical has mirrored the dagre output).
const LAYOUT_LANE_MAIN = "main_flow";
const LAYOUT_LANE_DEFAULT_OFFSET = -160; // fallback when layout_y_offset absent

function getMaxGraphHeight(): number {
  if (typeof window === "undefined") return 900;
  return Math.max(MIN_GRAPH_HEIGHT, Math.floor(window.innerHeight * 0.75));
}

function loadStoredGraphHeight(): number {
  if (typeof window === "undefined") return DEFAULT_GRAPH_HEIGHT;
  const raw = localStorage.getItem(GRAPH_HEIGHT_STORAGE_KEY);
  if (!raw) return DEFAULT_GRAPH_HEIGHT;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return DEFAULT_GRAPH_HEIGHT;
  return Math.min(getMaxGraphHeight(), Math.max(MIN_GRAPH_HEIGHT, parsed));
}

function saveGraphHeight(height: number): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(GRAPH_HEIGHT_STORAGE_KEY, String(height));
}

function clampGraphHeight(height: number): number {
  return Math.min(getMaxGraphHeight(), Math.max(MIN_GRAPH_HEIGHT, height));
}

export function ReactorGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const lastTappedRef = useRef<{ nodeId: string; time: number } | null>(null);
  const tapTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const config = useConfigStore((s) => s.config);
  const setConfig = useConfigStore((s) => s.setConfig);

  // Node ids that are truly hidden from the visualisation: composite parents
  // whose unfolder produced visible child nodes.
  //
  // Detection heuristic: a skip_viz node is treated as a composite placeholder
  // (hidden) if it has at least one outgoing connection TO a node whose id
  // starts with the parent id followed by an underscore (e.g. cgr → cgr_seg1).
  // This distinguishes synthesized reactor children from independent same-group
  // nodes like pfr_ambient (which has an INCOMING wall connection FROM pfr, not
  // an outgoing connection to pfr, so the direction check filters it out).
  //
  // Nodes that are skip_viz but produce no such outgoing-to-child connections are
  // rendered normally (e.g. RefractoryReactor in A3/A4 whose segments are not
  // exposed as individual nodes in the visualisation).
  const trulyHiddenNodeIds = useMemo<Set<string>>(() => {
    const hidden = new Set<string>();
    for (const node of config.nodes) {
      if (!node.metadata?.skip_viz) continue;
      const prefix = `${node.id}_`;
      const hasChildConn = config.connections.some(
        (c) => c.source === node.id && c.target.startsWith(prefix),
      );
      if (hasChildConn) hidden.add(node.id);
    }
    return hidden;
  }, [config.nodes, config.connections]);
  const setSelectedElement = useSelectionStore((s) => s.setSelectedElement);
  const clearSelection = useSelectionStore((s) => s.clearSelection);
  const setActiveTab = useResultsTabStore((s) => s.setActiveTab);
  const theme = useThemeStore((s) => s.theme);
  const [graphHeight, setGraphHeight] = useState(loadStoredGraphHeight);

  // Topology fingerprint: sorted node-ids + connection-ids joined into a
  // string.  Changes only when nodes/connections are added or removed — not
  // when temperatures or properties are updated.  Used to skip full layout
  // re-runs when only data (e.g. temperature) changes post-simulation.
  const topoFingerprintRef = useRef<string>("");

  // Per-node "natural" (algorithm-computed) positions captured after every
  // layout pass, before manual offsets are applied.  Used by applyPinnedPositions
  // to compute absolute from relative, and by dragfree to store the offset.
  const naturalPosRef = useRef<Map<string, { x: number; y: number }>>(new Map());

  const handleResizePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startY = event.clientY;
      const startHeight = graphHeight;

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const delta = moveEvent.clientY - startY;
        setGraphHeight(clampGraphHeight(startHeight + delta));
      };

      const handlePointerUp = (upEvent: PointerEvent) => {
        const delta = upEvent.clientY - startY;
        const finalHeight = clampGraphHeight(startHeight + delta);
        saveGraphHeight(finalHeight);
        setGraphHeight(finalHeight);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
      };

      document.body.style.cursor = "ns-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
    },
    [graphHeight],
  );

  // Build cytoscape elements from config.
  // Stream-point diamonds (inter-stage connectors) are NOT assigned a parent
  // group — they float freely between stage boxes.  alignLayoutLanes places
  // them at the midpoint between their source and target main-flow nodes, so
  // they sit visually on the edge that connects two stage boxes.
  // Previously they were inside the source group (for dagre rank propagation),
  // but since alignLayoutLanes now computes ranks from config.connections
  // directly, that is no longer needed — and keeping the parent caused the
  // source group box to stretch to include the diamond.
  //
  // Pre-simulation synthesis: when the config has inter-stage connections but no
  // stream-point nodes yet, the diamond nodes and two-hop edges are synthesised
  // here so the initial graph matches the post-simulation topology.  The config
  // is never mutated — synthesis is purely for display.
  const buildElements = useCallback(() => {
    const elements: cytoscape.ElementDefinition[] = [];
    const createdGroups = new Set<string>();
    // Track node ids actually added to elements so we can guard edges below.
    const renderedNodeIds = new Set<string>();

    // --- helper: ensure a group compound node exists ---
    const ensureGroup = (groupName: string) => {
      const parentId = `group:${groupName}`;
      if (!createdGroups.has(parentId)) {
        createdGroups.add(parentId);
        elements.push({ data: { id: parentId, label: groupName, isGroup: true } });
      }
    };

    // --- build node-to-group map and find existing stream-point ids ---
    const nodeToGroup = new Map<string, string>();
    const existingStreamIds = new Set<string>();
    for (const node of config.nodes) {
      const grp = String(
        node.group ?? node.properties?.group ?? node.properties?.group_name ?? "",
      ).trim();
      if (grp) nodeToGroup.set(node.id, grp);
      if (node.properties?.stream_point || node.metadata?.stream_point) {
        existingStreamIds.add(node.id);
      }
    }

    // --- detect inter-stage connections needing synthesis ---
    // inter_by_src[sourceId] = list of original connection objects
    const interBySrc = new Map<string, typeof config.connections>();
    for (const conn of config.connections) {
      const srcGrp = nodeToGroup.get(conn.source);
      const tgtGrp = nodeToGroup.get(conn.target);
      const streamId = `${conn.source}_outlet`;
      if (
        srcGrp && tgtGrp && srcGrp !== tgtGrp &&
        !existingStreamIds.has(streamId) &&
        conn.type !== "StreamConnector"
      ) {
        if (!interBySrc.has(conn.source)) interBySrc.set(conn.source, []);
        interBySrc.get(conn.source)!.push(conn);
      }
    }
    const replacedConnIds = new Set(
      [...interBySrc.values()].flatMap((cs) => cs.map((c) => c.id)),
    );

    // --- emit config nodes ---
    for (const node of config.nodes) {
      // Composite placeholder nodes (unfolded into visible children) are hidden
      // so the children are shown in their place inside the group box.
      // Nodes whose unfolder produced no visible children are rendered normally
      // (see trulyHiddenNodeIds memo above for the exact condition).
      if (trulyHiddenNodeIds.has(node.id)) continue;

      const isStreamPoint =
        Boolean(node.properties?.stream_point) ||
        Boolean(node.metadata?.stream_point);

      const upstreamStage = isStreamPoint
        ? String(
            node.properties?.upstream_stage ??
              node.metadata?.upstream_stage ??
              "",
          ).trim()
        : "";

      const group = String(
        node.group ??
          node.properties?.group ??
          node.properties?.group_name ??
          upstreamStage,
      ).trim();

      if (group) ensureGroup(group);

      const streamLabel = isStreamPoint
        ? node.id
            .replace(/_outlet$/, " Outlet")
            .split("_")
            .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
            .join(" ")
        : node.id;

      // Stream-point diamonds float freely (no parent group) so the source
      // stage box does not stretch to include them.  All other nodes keep their
      // group parent for compound-node box rendering.
      const nodeData: Record<string, unknown> = {
        id: node.id,
        label: streamLabel,
        type: node.type,
        temperature: Number(node.properties?.temperature ?? 300),
        ...(!isStreamPoint && group ? { parent: `group:${group}` } : {}),
      };
      if (isStreamPoint) nodeData.stream_point = true;
      elements.push({ data: nodeData });
      renderedNodeIds.add(node.id);
    }

    // --- synthesise placeholder stream-point diamond nodes (pre-simulation) ---
    // No parent: diamonds float freely between stage groups (see comment above).
    for (const [src, _conns] of interBySrc) {
      const streamId = `${src}_outlet`;
      const streamLabel = streamId
        .replace(/_outlet$/, " Outlet")
        .split("_")
        .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
      elements.push({
        data: {
          id: streamId,
          label: streamLabel,
          type: "Reservoir",
          stream_point: true,
          temperature: 300,
          // No parent — diamond sits freely between source and target groups.
        },
      });
      renderedNodeIds.add(streamId);
    }

    // Build skip_viz set (restricted to truly hidden nodes — those with unfolded
    // children) and raw forward adjacency for pass-through resolution.
    const skipVizNodeIds = new Set(trulyHiddenNodeIds);
    const rawFwdAdj = new Map<string, string[]>();
    for (const conn of config.connections) {
      if (!rawFwdAdj.has(conn.source)) rawFwdAdj.set(conn.source, []);
      rawFwdAdj.get(conn.source)!.push(conn.target);
    }

    // Follow skip_viz chains from `start` and collect the first rendered successors.
    const resolveRenderedSuccessors = (start: string): string[] => {
      const visited = new Set<string>();
      const result: string[] = [];
      const stack = [start];
      while (stack.length > 0) {
        const cur = stack.pop()!;
        if (visited.has(cur)) continue;
        visited.add(cur);
        for (const nb of rawFwdAdj.get(cur) ?? []) {
          if (renderedNodeIds.has(nb)) {
            result.push(nb);
          } else if (skipVizNodeIds.has(nb)) {
            stack.push(nb);
          }
        }
      }
      return result;
    };

    // --- emit config edges, skipping replaced inter-stage MFCs ---
    const emittedPassThroughEdges = new Set<string>();
    for (const conn of config.connections) {
      if (replacedConnIds.has(conn.id)) continue;
      if (!renderedNodeIds.has(conn.source)) continue;

      if (renderedNodeIds.has(conn.target)) {
        // Normal edge: both endpoints rendered.
        elements.push({
          data: {
            id: conn.id,
            label: conn.id,
            source: conn.source,
            target: conn.target,
            type: conn.type,
          },
        });
      } else if (skipVizNodeIds.has(conn.target)) {
        // Pass-through: target is hidden — emit a synthetic dashed edge to each
        // visible successor reachable through the hidden chain.
        for (const visTarget of resolveRenderedSuccessors(conn.target)) {
          const synId = `${conn.id}__pt__${visTarget}`;
          if (!emittedPassThroughEdges.has(synId)) {
            emittedPassThroughEdges.add(synId);
            elements.push({
              data: {
                id: synId,
                label: "",
                source: conn.source,
                target: visTarget,
                type: conn.type,
                passThrough: true,
              },
            });
          }
        }
      }
    }

    // --- synthesise stream-point display edges (pre-simulation) ---
    for (const [src, conns] of interBySrc) {
      // Guard: if the source node was not rendered (e.g. hidden composite
      // placeholder), skip the entire two-hop chain for this source.
      if (!renderedNodeIds.has(src)) continue;

      const streamId = `${src}_outlet`;
      elements.push({
        data: {
          id: `${src}_to_${streamId}`,
          label: `${src}_to_${streamId}`,
          source: src,
          target: streamId,
          type: "StreamConnector",
        },
      });
      renderedNodeIds.add(streamId);
      for (const conn of conns) {
        // Guard: skip the downstream hop if the target is hidden.
        if (!renderedNodeIds.has(conn.target)) continue;
        elements.push({
          data: {
            id: `${streamId}_to_${conn.target}`,
            label: `${streamId}_to_${conn.target}`,
            source: streamId,
            target: conn.target,
            type: "MassFlowController",
          },
        });
      }
    }

    return elements;
  }, [config, trulyHiddenNodeIds]);

  // Build stylesheet
  const buildStylesheet = useCallback((): any => {
    const isDark = theme === "dark";
    return [
      {
        selector: "node",
        style: {
          content: "data(label)",
          "text-valign": "center",
          "text-halign": "center",
          "background-color":
            "mapData(temperature, 300, 2273, deepskyblue, tomato)",
          "text-outline-color": "#555",
          "text-outline-width": 2,
          color: "#fff",
          width: 80,
          height: 80,
          "text-wrap": "wrap",
          "text-max-width": "80px",
        },
      },
      {
        selector: "node[isGroup]",
        style: {
          shape: "round-rectangle",
          "background-opacity": 0.05,
          "background-color": isDark ? "#666" : "#999",
          "border-width": 2,
          "border-color": isDark ? "#666" : "#999",
          "text-valign": "top",
          "text-halign": "center",
          padding: "20px",
        },
      },
      {
        // Non-group nodes default to ellipse (round).
        // Subsequent rules override this for Reservoir (octagon) and
        // stream-point (diamond) nodes via cascade specificity.
        // [^isGroup] matches nodes where isGroup is undefined — i.e. all
        // non-compound nodes.  :not([isGroup]) is unsupported in Cytoscape.js.
        selector: "node[^isGroup]",
        style: { shape: "ellipse" },
      },
      {
        // Boundary Reservoir nodes (feed tanks, sinks) use octagon.
        selector: "[type='Reservoir']",
        style: { shape: "octagon" },
      },
      {
        // PFR-derived reactor types (tube-like, axial-flow) use a wide
        // horizontal rectangle to visually distinguish them from stirred
        // reactors (ellipse) and boundary nodes (octagon).  All types that
        // inherit from PFR-style axial reactors are listed here; add new ones as needed.
        selector: [
          "RefractoryReactor",
          "TubeFurnace",
          "PFRHomogeneousShell",
          "PFRThinShell",
          "PFRGasTemperatureProfile",
          "PFRWallProfile",
        ].map((t) => `[type='${t}']`).join(", "),
        style: {
          shape: "rectangle",
          width: "120px",
          height: "48px",
        },
      },
      {
        // Stream-point Reservoirs (P&ID diamonds at stage boundaries).
        // [?stream_point] matches nodes where the key is present (and truthy),
        // which is unambiguous — only set for stream-point nodes.
        // Must follow [type = 'Reservoir'] to override its octagon shape.
        selector: "[?stream_point]",
        style: { shape: "diamond", width: "60px", height: "60px" },
      },
      {
        selector: "edge",
        style: {
          width: 3,
          "line-color": isDark ? "#888" : "#999",
          "target-arrow-color": isDark ? "#888" : "#999",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          label: "data(label)",
          "font-size": "11px",
          "text-rotation": "none",
          "text-margin-y": -10,
          color: isDark ? "#ccc" : "#555",
        },
      },
      {
        // StreamConnector: display-only material stream edge from source reactor
        // to stream-point diamond.  Solid line per P&ID convention for material
        // streams.  No label to avoid clutter at stage boundaries.
        selector: "[type='StreamConnector']",
        style: {
          width: 2,
          "line-style": "solid",
          "target-arrow-shape": "triangle",
          label: "",
          "line-color": isDark ? "#888" : "#999",
          "target-arrow-color": isDark ? "#888" : "#999",
        },
      },
      {
        // Wall: energy/heat stream per P&ID convention — dashed line, orange
        // tint to distinguish from material streams.  Arrow points from the
        // process side (reactor) toward the heat sink (ambient).
        selector: "[type='Wall']",
        style: {
          width: 1.5,
          "line-style": "dashed",
          "line-dash-pattern": [8, 4],
          "target-arrow-shape": "triangle",
          "line-color": isDark ? "#e07b39" : "#c0622a",
          "target-arrow-color": isDark ? "#e07b39" : "#c0622a",
        },
      },
      {
        // Pass-through: synthetic edge short-circuiting a hidden (skip_viz) node.
        // Rendered as a faint dotted line so the flow path is traceable without
        // implying a direct physical connection.
        selector: "[?passThrough]",
        style: {
          width: 1,
          "line-style": "dotted",
          "line-dash-pattern": [4, 6],
          "target-arrow-shape": "triangle",
          "line-color": isDark ? "#666" : "#aaa",
          "target-arrow-color": isDark ? "#666" : "#aaa",
          opacity: 0.6,
          label: "",
        },
      },
      {
        selector: ":selected",
        style: {
          "border-width": 4,
          "border-color": "#0d6efd",
        },
      },
    ];
  }, [theme]);

  // Dagre LR layout stacks sibling stages bottom-to-top; mirror Y so flow reads top-to-bottom.
  const flipLayoutVertical = useCallback((cy: Core): void => {
    const nodes = cy.nodes();
    if (nodes.length === 0) return;

    let minY = Infinity;
    let maxY = -Infinity;
    nodes.forEach((node) => {
      const y = node.position().y;
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    });
    const centerY = (minY + maxY) / 2;

    nodes.forEach((node) => {
      const pos = node.position();
      node.position({ x: pos.x, y: centerY - (pos.y - centerY) });
    });
  }, []);

  // Infer swim-lane assignments from network topology when no explicit
  // layout_lane metadata is present in the config.
  //
  // Algorithm:
  //   1. Build a DAG over all rendered non-group, non-stream-point nodes using
  //      config.connections (same _outlet alias collapsing as alignLayoutLanes).
  //   2. Find the longest source-to-sink path (DP on topo order).  Tie-break:
  //      prefer reactor-type nodes (non-Reservoir / non-OutletSink) over boundary
  //      nodes; then stable declaration order.  This path becomes "main_flow".
  //   3. All other nodes are "auto_branch".  Each branch node is anchored to its
  //      closest spine neighbor: prefer the spine node it connects INTO; fall back
  //      to the spine node that connects INTO it.
  //
  // Stream-point diamonds and group compound nodes are excluded — they are handled
  // separately by Steps 3.6 and 5 of alignLayoutLanes.
  //
  // Returns { lanes: Map<id,lane>, anchors: Map<branchId, spineId> }.
  // Both maps are empty if the graph has no nodes.
  const inferLanesFromTopology = useCallback(
    (cy: Core): { lanes: Map<string, string>; anchors: Map<string, string> } => {
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
      const skipVizIds = trulyHiddenNodeIds;

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

      // Build a raw adjacency map over ALL config.connections (including those
      // involving hidden nodes) so we can resolve transitive paths.
      const rawOut = new Map<string, string[]>();
      for (const conn of config.connections) {
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

      for (const conn of config.connections) {
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
      // Stable initial ordering by declaration order in config.nodes.
      const declOrder = new Map<string, number>();
      config.nodes.forEach((n, i) => declOrder.set(n.id, i));
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
      for (const id of candidateIds) {
        if (!topoOrder.includes(id)) topoOrder.push(id);
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
      const pathLen = new Map<string, number>();
      const pathPrev = new Map<string, string | null>();
      for (const id of topoOrder) {
        let best = 0;
        let bestPrev: string | null = null;
        // Walk all predecessors (nodes with an edge to id).
        for (const pred of topoOrder) {
          if ((outEdges.get(pred) ?? []).includes(id)) {
            const val = (pathLen.get(pred) ?? 0) + spineWeight(id);
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

      // Assign lanes.
      const lanes = new Map<string, string>();
      for (const id of candidateIds) {
        lanes.set(id, spineSet.has(id) ? LAYOUT_LANE_MAIN : "auto_branch");
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
    },
    [config.nodes, config.connections, trulyHiddenNodeIds],
  );

  // Align layout-lane nodes into clean rows.
  //
  // After dagre's compound-graph layout (which produces a diagonal staircase
  // for multi-stage configs), this pass enforces:
  //   1. All "main_flow" nodes → same Y (median of their dagre Ys).
  //   2. All non-main-flow nodes (injection feeds, etc.) →
  //        X = X of their downstream main_flow target (so they appear
  //            directly above the mixer they feed, not to the left),
  //        Y = mainFlowY + LAYOUT_LANE_DEFAULT_OFFSET (one row above).
  //   3. Group compound nodes → repositioned to wrap their (now moved)
  //      children so stage boxes stay flush around the aligned nodes.
  //
  // "Downstream target" is resolved by walking config.connections: the first
  // MassFlowController whose source is the non-main node and whose target has
  // a main_flow lane determines the X anchor.
  const alignLayoutLanes = useCallback((cy: Core): void => {
    // -------------------------------------------------------------------------
    // Step 0: Build helper maps from the config metadata.
    //
    // layout_lane:     swim-lane id ("main_flow" = horizontal baseline).
    // layout_y_offset: Y offset (px) relative to mainFlowY; negative = above.
    //                  Falls back to LAYOUT_LANE_DEFAULT_OFFSET when absent.
    // layout_x_offset: X offset (px) relative to the downstream main-flow node.
    //                  Falls back to 0 when absent.
    // layout_order:    integer rank override for main-flow node ordering.
    //                  When absent, rank is determined by Kahn's topo-sort.
    // -------------------------------------------------------------------------
    const nodeToLane = new Map<string, string>();
    const nodeToYOffset = new Map<string, number>();
    const nodeToXOffset = new Map<string, number>();
    const nodeToOrder = new Map<string, number>();
    const nodeToAnchor = new Map<string, string>(); // explicit layout_anchor override
    for (const node of config.nodes) {
      if (node.metadata?.skip_viz) continue; // placeholder nodes are not rendered
      const lane = String(node.metadata?.layout_lane ?? "").trim();
      if (lane) nodeToLane.set(node.id, lane);
      const yOff = node.metadata?.layout_y_offset;
      if (typeof yOff === "number" && Number.isFinite(yOff)) nodeToYOffset.set(node.id, yOff);
      const xOff = node.metadata?.layout_x_offset;
      if (typeof xOff === "number" && Number.isFinite(xOff)) nodeToXOffset.set(node.id, xOff);
      const ord = node.metadata?.layout_order;
      if (typeof ord === "number" && Number.isFinite(ord)) nodeToOrder.set(node.id, ord);
      const anchor = node.metadata?.layout_anchor;
      if (typeof anchor === "string" && anchor.trim()) nodeToAnchor.set(node.id, anchor.trim());
    }
    // When no explicit layout_lane is declared, infer the main-flow spine and
    // branch nodes from the network topology so simple models (SPRING_A3, A4)
    // get an organised layout without any YAML metadata.
    let inferredAnchors: Map<string, string> | null = null;
    if (nodeToLane.size === 0) {
      const inferred = inferLanesFromTopology(cy);
      if (inferred.lanes.size === 0) return; // truly empty graph
      inferred.lanes.forEach((lane, id) => nodeToLane.set(id, lane));
      inferredAnchors = inferred.anchors;
    }

    // -------------------------------------------------------------------------
    // Step 1: Topology-sort the MAIN-FLOW nodes using config.connections to
    //         produce a deterministic left-to-right column (rank) order.
    //
    //         We use Kahn's algorithm on the subgraph of main_flow nodes.
    //         The resulting order is translated into evenly-spaced X positions,
    //         overriding whatever dagre assigned.  This is necessary because
    //         cytoscape-dagre treats compound groups as first-class nodes when
    //         assigning ranks, which causes cross-stage edges to push each stage
    //         group into its own rank → staircase.  By computing ranks ourselves
    //         from the logical config topology we get a flat, correct ordering.
    // -------------------------------------------------------------------------
    const mainFlowIds = new Set<string>();
    cy.nodes().forEach((n) => {
      if (!n.data("isGroup") && nodeToLane.get(n.id()) === LAYOUT_LANE_MAIN) {
        mainFlowIds.add(n.id());
      }
    });

    // Build a raw adjacency map for ALL config.connections (including those
    // through hidden nodes) so we can resolve transitive paths in Step 1.
    // This mirrors the short-circuit used in inferLanesFromTopology.
    const skipVizIdsMF = trulyHiddenNodeIds;
    const rawConnOutMF = new Map<string, string[]>();
    for (const conn of config.connections) {
      const src = conn.source.endsWith("_outlet")
        ? conn.source.slice(0, -"_outlet".length)
        : conn.source;
      if (!rawConnOutMF.has(src)) rawConnOutMF.set(src, []);
      rawConnOutMF.get(src)!.push(conn.target);
    }

    // Follow skip_viz chains from `start` and collect the first mainFlowIds
    // successors (those not hidden).
    const resolveMainFlowSuccessors = (start: string): string[] => {
      const visited = new Set<string>();
      const result: string[] = [];
      const stack = [start];
      while (stack.length > 0) {
        const cur = stack.pop()!;
        if (visited.has(cur)) continue;
        visited.add(cur);
        for (const nb of rawConnOutMF.get(cur) ?? []) {
          if (mainFlowIds.has(nb)) {
            result.push(nb);
          } else if (skipVizIdsMF.has(nb)) {
            stack.push(nb);
          }
        }
      }
      return result;
    };

    // Build adjacency for the main-flow sub-graph.
    // For cross-stage connections we use the full config.connections list;
    // for intra-stage edges the cy graph already has them.
    // Connections passing through skip_viz (hidden) nodes are short-circuited.
    const outEdges = new Map<string, string[]>();
    const inDegree = new Map<string, number>();
    for (const id of mainFlowIds) {
      outEdges.set(id, []);
      inDegree.set(id, 0);
    }
    const addEdge = (src: string, tgt: string) => {
      if (!mainFlowIds.has(src) || !mainFlowIds.has(tgt)) return;
      if (!outEdges.get(src)!.includes(tgt)) {
        outEdges.get(src)!.push(tgt);
        inDegree.set(tgt, (inDegree.get(tgt) ?? 0) + 1);
      }
    };
    for (const conn of config.connections) {
      const srcRaw = conn.source.endsWith("_outlet")
        ? conn.source.slice(0, -"_outlet".length)
        : conn.source;
      if (mainFlowIds.has(srcRaw)) {
        if (mainFlowIds.has(conn.target)) {
          addEdge(srcRaw, conn.target);
        } else if (skipVizIdsMF.has(conn.target)) {
          for (const succ of resolveMainFlowSuccessors(conn.target)) {
            addEdge(srcRaw, succ);
          }
        }
      }
    }
    cy.edges().forEach((e) => {
      addEdge(e.source().id(), e.target().id());
    });

    // Kahn's topological sort (BFS) — nodes with layout_order metadata are
    // sorted by that value and interleaved with topo-sort for the rest.
    const order: string[] = [];
    const queue: string[] = [];
    for (const id of mainFlowIds) {
      if ((inDegree.get(id) ?? 0) === 0) queue.push(id);
    }
    // Sort the initial zero-in-degree set by layout_order if provided.
    queue.sort((a, b) => (nodeToOrder.get(a) ?? Infinity) - (nodeToOrder.get(b) ?? Infinity));
    while (queue.length > 0) {
      const cur = queue.shift()!;
      order.push(cur);
      const nextBatch: string[] = [];
      for (const next of outEdges.get(cur) ?? []) {
        const deg = (inDegree.get(next) ?? 0) - 1;
        inDegree.set(next, deg);
        if (deg === 0) nextBatch.push(next);
      }
      // Respect layout_order within each BFS level.
      nextBatch.sort((a, b) => (nodeToOrder.get(a) ?? Infinity) - (nodeToOrder.get(b) ?? Infinity));
      queue.push(...nextBatch);
    }
    // Any remaining (cycles / unreachable) appended in layout_order then stable order.
    const remaining = [...mainFlowIds].filter((id) => !order.includes(id));
    remaining.sort((a, b) => (nodeToOrder.get(a) ?? Infinity) - (nodeToOrder.get(b) ?? Infinity));
    order.push(...remaining);

    // Assign evenly-spaced X positions starting from a fixed left anchor.
    // cy.fit() called after this function centres the viewport on the graph,
    // so absolute coordinates don't matter — we just need consistent spacing.
    const X_STEP = 320;   // horizontal spacing between main-flow columns [px]
    // Left padding keeps everything in positive coords.
    const X_ANCHOR = 300;
    const xForMainNode = new Map<string, number>();
    order.forEach((id, idx) => {
      xForMainNode.set(id, X_ANCHOR + idx * X_STEP);
    });

    // -------------------------------------------------------------------------
    // Step 2: Choose a common Y for all main-flow nodes (use median from dagre
    //         so we don't clash with the surrounding groups).
    // -------------------------------------------------------------------------
    const mainYs: number[] = [];
    cy.nodes().forEach((n) => {
      if (!n.data("isGroup") && mainFlowIds.has(n.id())) {
        mainYs.push(n.position().y);
      }
    });
    if (mainYs.length === 0) return;
    const sortedYs = [...mainYs].sort((a, b) => a - b);
    const mid = Math.floor(sortedYs.length / 2);
    const mainFlowY =
      sortedYs.length % 2 === 0
        ? (sortedYs[mid - 1] + sortedYs[mid]) / 2
        : sortedYs[mid];

    // -------------------------------------------------------------------------
    // Step 3: Position all main-flow nodes.
    // -------------------------------------------------------------------------
    cy.nodes().forEach((n) => {
      if (n.data("isGroup") || !mainFlowIds.has(n.id())) return;
      const x = xForMainNode.get(n.id()) ?? n.position().x;
      n.position({ x, y: mainFlowY });
    });

    // -------------------------------------------------------------------------
    // Step 3.6: Stream-point outlet diamonds ({src}_outlet).
    //
    //           Place each diamond at mainFlowY, X = midpoint between its source
    //           main-flow node and its downstream main-flow target.  This puts it
    //           visually between the two stage boxes, horizontally centred on the
    //           edge it represents.
    //
    //           Build the source→target map from config connections first.
    // -------------------------------------------------------------------------
    // Map: streamId ("X_outlet") → downstream main-flow target id
    const outletToTarget = new Map<string, string>();
    for (const conn of config.connections) {
      // Direct inter-stage: source = "X_outlet", target = "Y"
      if (conn.source.endsWith("_outlet") && mainFlowIds.has(conn.target)) {
        outletToTarget.set(conn.source, conn.target);
      }
      // Synthesised alias path: source = "X", target = "Y" (cross-stage MFC)
      // → synthesised stream-point id is "X_outlet"
      if (mainFlowIds.has(conn.source) && mainFlowIds.has(conn.target)) {
        const syntheticId = `${conn.source}_outlet`;
        if (!outletToTarget.has(syntheticId)) {
          outletToTarget.set(syntheticId, conn.target);
        }
      }
      // Short-circuit through hidden (skip_viz) targets: if source is mainFlow
      // and target is hidden, resolve the first visible mainFlow successor.
      if (mainFlowIds.has(conn.source) && skipVizIdsMF.has(conn.target)) {
        const syntheticId = `${conn.source}_outlet`;
        if (!outletToTarget.has(syntheticId)) {
          const succs = resolveMainFlowSuccessors(conn.target);
          if (succs.length > 0) outletToTarget.set(syntheticId, succs[0]);
        }
      }
    }
    cy.nodes().forEach((n) => {
      if (n.data("isGroup") || !n.data("stream_point")) return;
      const id = n.id();
      if (!id.endsWith("_outlet")) return;
      const srcId = id.slice(0, -"_outlet".length);
      const srcX = xForMainNode.get(srcId);
      const tgtId = outletToTarget.get(id);
      const tgtX = tgtId ? xForMainNode.get(tgtId) : undefined;
      let x: number;
      if (srcX !== undefined && tgtX !== undefined) {
        // Midpoint between source reactor and downstream reactor.
        x = (srcX + tgtX) / 2;
      } else if (srcX !== undefined) {
        // No downstream found — place slightly to the right of the source.
        x = srcX + X_STEP / 2;
      } else {
        x = n.position().x; // fallback: keep dagre X
      }
      n.position({ x, y: mainFlowY });
    });

    // -------------------------------------------------------------------------
    // Step 4: Non-main-flow nodes → placed relative to their downstream
    //         main_flow target using per-node metadata offsets.
    //
    //   layout_anchor:   explicit id of a main_flow node to anchor to (highest priority).
    //   layout_y_offset: Y distance from mainFlowY (px). Default: LAYOUT_LANE_DEFAULT_OFFSET.
    //   layout_x_offset: X shift from the target node's X (px). Default: 0.
    //
    // Also handles nodes without a layout_lane that carry layout_y_offset
    // metadata (e.g. synthesised side-branch reservoirs injected by plugin builders).
    // -------------------------------------------------------------------------
    const nonMainToTarget = new Map<string, string>();
    // Honour explicit layout_anchor overrides first.
    nodeToAnchor.forEach((anchorId, nodeId) => {
      nonMainToTarget.set(nodeId, anchorId);
    });
    // Seed from inferred topology anchors (auto-inference mode only).
    // Explicit layout_anchor in metadata takes precedence (already populated above).
    if (inferredAnchors) {
      inferredAnchors.forEach((spineId, branchId) => {
        if (!nonMainToTarget.has(branchId)) {
          nonMainToTarget.set(branchId, spineId);
        }
      });
    }
    for (const conn of config.connections) {
      const srcLane = nodeToLane.get(conn.source);
      const tgtLane = nodeToLane.get(conn.target);
      if (srcLane && srcLane !== LAYOUT_LANE_MAIN && tgtLane === LAYOUT_LANE_MAIN) {
        nonMainToTarget.set(conn.source, conn.target);
      }
      // Also map un-laned nodes that have an explicit layout_y_offset to their
      // nearest main-flow connection partner (source or target).
      if (nodeToYOffset.has(conn.source) && !nodeToAnchor.has(conn.source)) {
        if (!nodeToLane.has(conn.source) && mainFlowIds.has(conn.target)) {
          if (!nonMainToTarget.has(conn.source)) {
            nonMainToTarget.set(conn.source, conn.target);
          }
        }
      }
      if (nodeToYOffset.has(conn.target) && !nodeToAnchor.has(conn.target)) {
        if (!nodeToLane.has(conn.target) && mainFlowIds.has(conn.source)) {
          if (!nonMainToTarget.has(conn.target)) {
            nonMainToTarget.set(conn.target, conn.source);
          }
        }
      }
    }
    cy.nodes().forEach((n) => {
      if (n.data("isGroup")) return;
      const id = n.id();
      const lane = nodeToLane.get(id);
      const hasYOffset = nodeToYOffset.has(id);
      // Skip main-flow nodes and nodes with neither a non-main lane nor a y-offset.
      if (lane === LAYOUT_LANE_MAIN) return;
      if (!lane && !hasYOffset) return;
      if (n.data("stream_point")) return; // stream-point outlets handled in Step 3.6

      const yOffset = nodeToYOffset.has(id) ? nodeToYOffset.get(id)! : LAYOUT_LANE_DEFAULT_OFFSET;
      const xOffset = nodeToXOffset.get(id) ?? 0;
      const targetId = nonMainToTarget.get(id);
      const targetX = targetId
        ? (xForMainNode.get(targetId) ?? cy.getElementById(targetId).position().x)
        : n.position().x;
      n.position({ x: targetX + xOffset, y: mainFlowY + yOffset });
    });

    // -------------------------------------------------------------------------
    // Step 5: Let Cytoscape auto-refit compound (group) nodes.
    //
    //         Compound node position in Cytoscape is *computed* from the
    //         bounding box of its children — calling .position() on a compound
    //         node shifts the children (see `beforePositionSet` in core), so we
    //         must NOT set it here after already repositioning children.
    //
    //         Remove any explicit width/height that dagre injected so that
    //         Cytoscape's auto-sizing re-engages and the group border correctly
    //         wraps the (now moved) children on the next render.
    // -------------------------------------------------------------------------
    cy.nodes("[isGroup]").removeStyle("width height");

  }, [config.nodes, config.connections, trulyHiddenNodeIds, inferLanesFromTopology]);

  // Nudge nodes that share the same position to avoid "invalid endpoints" edge warnings
  const nudgeOverlappingNodes = useCallback((cy: Core): void => {
    const NUDGE = 25;
    const positions = new Map<string, string[]>();
    cy.nodes().forEach((node) => {
      if (node.data("isGroup")) return;
      const pos = node.position();
      const key = `${pos.x.toFixed(2)},${pos.y.toFixed(2)}`;
      if (!positions.has(key)) positions.set(key, []);
      positions.get(key)!.push(node.id());
    });
    positions.forEach((nodeIds, _key) => {
      if (nodeIds.length <= 1) return;
      nodeIds.slice(1).forEach((id, i) => {
        const node = cy.getElementById(id);
        const pos = node.position();
        node.position({ x: pos.x + (i + 1) * NUDGE, y: pos.y + (i + 1) * NUDGE });
      });
    });
  }, []);

  // Apply manual drag offsets (metadata.layout_offset {dx, dy}) on top of each
  // node's algorithmically computed "natural" position stored in naturalPosRef.
  // This makes persisted positions topology-independent: the node tracks its
  // neighbors when the graph re-lays-out rather than jumping to a stale absolute.
  const applyPinnedPositions = useCallback(
    (cy: Core) => {
      for (const node of config.nodes) {
        const off = node.metadata?.layout_offset as { dx: number; dy: number } | undefined;
        if (off && Number.isFinite(off.dx) && Number.isFinite(off.dy)) {
          const nat = naturalPosRef.current.get(node.id);
          const n = cy.getElementById(node.id);
          if (n.length && !n.data("isGroup") && nat) {
            n.position({ x: nat.x + off.dx, y: nat.y + off.dy });
          }
        }
      }
    },
    [config],
  );

  const runGraphLayout = useCallback(
    (cy: Core, animate = false) => {
      // Run dagre on leaf nodes only — exclude compound group nodes from rank

      // assignment so cross-stage edges do not force groups into a staircase.
      // We collect X positions from the dagre pass, then alignLayoutLanes does
      // the Y snapping and our post-pass re-centers the group boxes.
      const layout = cy.layout({
        name: "dagre",
        rankDir: "LR",
        nodeSep: 120,
        rankSep: 200,
        // Treat compound parents as transparent: rank only leaf nodes.
        // cytoscape-dagre exposes this via the undocumented `compound` flag.
        compound: false,
        animate,
        animationDuration: animate ? 300 : 0,
      } as any);
      layout.run();
      return layout.promiseOn("layoutstop").then(() => {
        flipLayoutVertical(cy);
        alignLayoutLanes(cy);
        nudgeOverlappingNodes(cy);
        // Snapshot the pin-free algorithmic positions before applying any
        // manual offsets.  dragfree reads this to compute layout_offset;
        // applyPinnedPositions reads it to reconstruct absolute position.
        naturalPosRef.current = new Map();
        cy.nodes().forEach((n) => {
          if (!n.data("isGroup")) naturalPosRef.current.set(n.id(), { ...n.position() });
        });
        // Re-apply any pinned positions (metadata.layout_offset) so manually
        // dragged nodes are not overwritten by dagre / alignLayoutLanes.
        applyPinnedPositions(cy);
        // Defer fit() by one animation frame so Cytoscape finishes recomputing
        // compound bounding boxes (auto-width/height from removeStyle) before
        // the viewport fits.  Without the deferral the leftmost group (which
        // includes unlabelled siblings at a negative-ish X) gets clipped.
        // Force Cytoscape to recompute compound bounding boxes before fitting.
        // updateCompoundBounds() is an internal method (not in public types)
        // that recalculates auto-size after removeStyle("width height").
        cy.nodes("[isGroup]").forEach((n) => (n as any).updateCompoundBounds?.());
        cy.forceRender();
        requestAnimationFrame(() => {
          cy.nodes("[isGroup]").forEach((n) => (n as any).updateCompoundBounds?.());
          cy.fit(undefined, 100);
        });
      });
    },
    [flipLayoutVertical, alignLayoutLanes, nudgeOverlappingNodes, applyPinnedPositions],
  );

  // Initialize cytoscape
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: buildElements(),
      style: buildStylesheet() as any,
      minZoom: 0.3,
      maxZoom: 3,
      userPanningEnabled: true,
      userZoomingEnabled: true,
    });

    cy.on("tap", "node", (e: EventObject) => {
      const data = e.target.data();
      if (data.isGroup) {
        // Compound group box tapped — select the group so the Plots tab
        // can show the stage-level aggregated profile (e.g. full CGR).
        // Use the plain stage name (strip "group:" prefix) as the id so
        // it aligns with reactors_series keys produced by the backend.
        const rawId = String(data.id ?? "");
        const stageId = rawId.startsWith("group:") ? rawId.slice("group:".length) : rawId;
        setSelectedElement({
          type: "node",
          data: { ...data, id: stageId, isGroup: true, label: stageId },
        });
        return;
      }
      const nodeId = String(data.id);
      const now = Date.now();
      const last = lastTappedRef.current;
      if (last?.nodeId === nodeId && now - last.time < DBLTAP_MS) {
        if (tapTimeoutRef.current) {
          clearTimeout(tapTimeoutRef.current);
          tapTimeoutRef.current = null;
        }
        lastTappedRef.current = null;
        setActiveTab("Thermo");
      } else {
        lastTappedRef.current = { nodeId, time: now };
        if (tapTimeoutRef.current) clearTimeout(tapTimeoutRef.current);
        tapTimeoutRef.current = setTimeout(() => {
          lastTappedRef.current = null;
          tapTimeoutRef.current = null;
        }, DBLTAP_MS);
      }
      setSelectedElement({ type: "node", data });
    });

    cy.on("tap", "edge", (e: EventObject) => {
      const data = e.target.data();
      setSelectedElement({ type: "edge", data });
      if (String(data.type) === "MassFlowController") {
        setActiveTab("Thermo");
      }
    });

    cy.on("tap", (e: EventObject) => {
      if (e.target === cy) clearSelection();
    });

    // Persist manually dragged positions as a relative offset from the node's
    // algorithmically computed "natural" position (metadata.layout_offset {dx,dy}).
    // Using useConfigStore.getState() to avoid stale closure captures.
    cy.on("dragfree", "node", (e: EventObject) => {
      const node = e.target;
      if (node.data("isGroup")) return;
      const id = node.id();
      const nat = naturalPosRef.current.get(id);
      if (!nat) return; // natural baseline not yet captured (layout not run yet)
      const { config: currentConfig, updateNode: updNode } = useConfigStore.getState();
      const existing = currentConfig.nodes.find((n) => n.id === id);
      if (!existing) return; // synthesized stream-point diamonds are not in config.nodes
      const p = node.position();
      updNode(id, {
        metadata: {
          ...(existing.metadata ?? {}),
          layout_offset: { dx: Math.round(p.x - nat.x), dy: Math.round(p.y - nat.y) },
        },
      });
    });

    cyRef.current = cy;

    return () => {
      if (tapTimeoutRef.current) {
        clearTimeout(tapTimeoutRef.current);
        tapTimeoutRef.current = null;
      }
      lastTappedRef.current = null;
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Compute topology fingerprint from sorted visible authored node ids only.
  //
  // Using nodes-only (not connections) avoids false fingerprint changes from the
  // staged solver's synthesize_stream_points step, which REMOVES the original
  // inter-stage connection dicts (e.g. "torch_to_tmr") and REPLACES them with
  // StreamConnector + inlet MFC pairs.  Those originals never come back in the
  // in-memory config, so any connection-based fingerprint would differ between
  // the pre-simulation state and the post-YAML-save state even when the authored
  // topology is identical.
  //
  // Layout positions are driven by node metadata (layout_lane, layout_x_offset…),
  // not by edge direction, so a connection-only change does not warrant a dagre
  // re-run anyway.
  const computeFingerprint = useCallback(() => {
    const nodeIds = config.nodes
      .filter((n) => !trulyHiddenNodeIds.has(n.id))
      .filter((n) => !n.properties?.stream_point && !n.metadata?.stream_point)
      .map((n) => n.id)
      .sort()
      .join(",");
    return nodeIds;
  }, [config, trulyHiddenNodeIds]);

  // Update elements when config changes.
  //
  // Strategy (GRAPH-01):
  //  - Compute topology fingerprint (sorted visible node ids, connections excluded
  //    because the staged solver removes and replaces inter-stage connection dicts
  //    during every build, making them an unreliable signal).
  //  - If fingerprint unchanged → only data or transient simulation artifacts
  //    changed (temperatures, stream-point nodes added/removed).
  //    Preserve the viewport (pan/zoom), do a full cy.json() element replace,
  //    then restore node positions from naturalPosRef + alignLayoutLanes +
  //    applyPinnedPositions, then restore pan/zoom.
  //    This is simpler and more correct than an incremental diff, which has
  //    hard-to-debug edge cases around compound nodes and synthesised edges.
  //  - If fingerprint changed (or first render) → run full dagre layout.
  const isFirstLayoutRef = useRef(true);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const newFingerprint = computeFingerprint();
    const isFirst = isFirstLayoutRef.current;

    if (!isFirst && newFingerprint === topoFingerprintRef.current) {
      // Authored topology unchanged — no dagre pass needed.
      // Save viewport, replace all elements (so synthesised edges are always
      // rebuilt correctly regardless of what the server put in config.connections),
      // restore positions, then restore pan/zoom so the user sees no jump.
      const pan = cy.pan();
      const zoom = cy.zoom();

      cy.json({ elements: buildElements() });

      // Restore natural positions (set during last full dagre layout).
      cy.nodes().forEach((n: cytoscape.NodeSingular) => {
        if (n.data("isGroup")) return;
        const nat = naturalPosRef.current.get(n.id());
        if (nat) n.position({ x: nat.x, y: nat.y });
      });
      // Re-run lane alignment (handles any new transient nodes not in naturalPosRef).
      alignLayoutLanes(cy);
      // Re-apply manual drag offsets from metadata.layout_offset.
      applyPinnedPositions(cy);
      cy.nodes("[isGroup]").removeStyle("width height");
      cy.nodes("[isGroup]").forEach((n: cytoscape.NodeSingular) => (n as any).updateCompoundBounds?.());

      // Restore viewport so the user sees no pan/zoom jump.
      cy.pan(pan);
      cy.zoom(zoom);
      cy.forceRender();
      return;
    }

    // Topology changed (or first render): replace elements and run layout.
    // We always do a full cy.json() replace on topology change — incremental
    // add/remove is error-prone when group compound nodes are involved (removing
    // children collapses the group; re-adding causes parent/child ordering issues).
    // cy.json() is safe here because this path only runs when the authored
    // topology actually changes (new/removed nodes in the YAML), not for
    // simulation-transient stream-point changes (excluded from fingerprint).
    topoFingerprintRef.current = newFingerprint;
    isFirstLayoutRef.current = false;

    cy.json({ elements: buildElements() });
    void runGraphLayout(cy, !isFirst);
  }, [buildElements, computeFingerprint, runGraphLayout]);

  // Update stylesheet when theme changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.style(buildStylesheet() as any);
  }, [buildStylesheet]);

  // Keep Cytoscape canvas in sync when the pane is resized
  useEffect(() => {
    cyRef.current?.resize();
  }, [graphHeight]);

  // Reset layout: remove all manual drag offsets and re-run full dagre pass.
  // Also strips legacy layout_pos keys written by the previous (broken)
  // absolute-coordinate implementation so old YAMLs are cleaned up on reset.
  const handleResetLayout = useCallback(() => {
    const currentConfig = useConfigStore.getState().config;
    const clearedNodes = currentConfig.nodes.map((n) => {
      if (n.metadata && ("layout_offset" in n.metadata || "layout_pos" in n.metadata)) {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { layout_offset, layout_pos, ...rest } = n.metadata as Record<string, unknown>;
        return { ...n, metadata: Object.keys(rest).length > 0 ? rest : null };
      }
      return n;
    });
    topoFingerprintRef.current = ""; // force full re-layout on next effect
    setConfig({ ...currentConfig, nodes: clearedNodes });
  }, [setConfig]);

  return (
    <div
      id="graph-container"
      className="relative overflow-hidden rounded-md border border-border"
      style={{ height: graphHeight }}
    >
      <div
        ref={containerRef}
        id="reactor-graph"
        className="h-full w-full"
        style={{ background: "var(--color-cytoscape-bg)" }}
        data-cy="graph"
      />
      {/* Reset layout button — only shown when manual drag offsets exist */}
      {config.nodes.some(
        (n) => n.metadata && ("layout_offset" in n.metadata || "layout_pos" in n.metadata),
      ) && (
        <button
          onClick={handleResetLayout}
          title="Reset graph layout"
          className="absolute top-2 right-2 z-10 rounded border border-border bg-background/80 px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        >
          Reset layout
        </button>
      )}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize network graph"
        aria-valuenow={graphHeight}
        aria-valuemin={MIN_GRAPH_HEIGHT}
        aria-valuemax={getMaxGraphHeight()}
        data-testid="graph-resize-handle"
        className="group absolute bottom-0 left-0 right-0 z-10 flex h-3 cursor-ns-resize items-center justify-center border-t border-border bg-background/80 touch-none hover:bg-accent/50"
        onPointerDown={handleResizePointerDown}
      >
        <span className="h-1 w-10 rounded-full bg-border transition-colors group-hover:bg-muted-foreground" />
      </div>
    </div>
  );
}
