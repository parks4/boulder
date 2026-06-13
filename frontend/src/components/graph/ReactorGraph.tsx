import { useEffect, useRef, useCallback, useState } from "react";
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
  const setSelectedElement = useSelectionStore((s) => s.setSelectedElement);
  const clearSelection = useSelectionStore((s) => s.clearSelection);
  const setActiveTab = useResultsTabStore((s) => s.setActiveTab);
  const theme = useThemeStore((s) => s.theme);
  const [graphHeight, setGraphHeight] = useState(loadStoredGraphHeight);

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
      // Composite placeholder nodes (unfolded into children) are hidden —
      // showing them as orphaned circles would distort compound bounding boxes.
      if (node.metadata?.skip_viz) continue;

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
    }

    // --- emit config edges, skipping replaced inter-stage MFCs ---
    for (const conn of config.connections) {
      if (replacedConnIds.has(conn.id)) continue;
      elements.push({
        data: {
          id: conn.id,
          label: conn.id,
          source: conn.source,
          target: conn.target,
          type: conn.type,
        },
      });
    }

    // --- synthesise stream-point display edges (pre-simulation) ---
    for (const [src, conns] of interBySrc) {
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
      for (const conn of conns) {
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
  }, [config]);

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
        // inherit from PFR in Bloc are listed here; add new ones as needed.
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
    if (nodeToLane.size === 0) return;

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

    // Build adjacency for the main-flow sub-graph.
    // For cross-stage connections we use the full config.connections list;
    // for intra-stage edges the cy graph already has them.
    const outEdges = new Map<string, string[]>();
    const inDegree = new Map<string, number>();
    for (const id of mainFlowIds) {
      outEdges.set(id, []);
      inDegree.set(id, 0);
    }
    const addEdge = (src: string, tgt: string) => {
      if (!mainFlowIds.has(src) || !mainFlowIds.has(tgt)) return;
      outEdges.get(src)!.push(tgt);
      inDegree.set(tgt, (inDegree.get(tgt) ?? 0) + 1);
    };
    for (const conn of config.connections) {
      addEdge(conn.source, conn.target);
      // "_outlet" alias: e.g. "reactor_outlet" → source="reactor", target="next_reactor"
      if (conn.source.endsWith("_outlet")) {
        addEdge(conn.source.slice(0, -"_outlet".length), conn.target);
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
  }, [config.nodes, config.connections]);

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
    [flipLayoutVertical, alignLayoutLanes, nudgeOverlappingNodes],
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

  // Update elements when config changes.
  // animate=false on first render so positions are applied immediately and
  // cy.fit() sees the correct final bounding box without racing the animation.
  const isFirstLayoutRef = useRef(true);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.json({ elements: buildElements() });
    const animate = !isFirstLayoutRef.current;
    isFirstLayoutRef.current = false;
    void runGraphLayout(cy, animate);
  }, [buildElements, runGraphLayout]);

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
