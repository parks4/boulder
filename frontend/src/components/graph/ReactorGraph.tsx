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
 * Uses dagre left-to-right layout.
 */
const DBLTAP_MS = 300;
const DEFAULT_GRAPH_HEIGHT = 360;
const MIN_GRAPH_HEIGHT = 240;
const GRAPH_HEIGHT_STORAGE_KEY = "boulder-graph-height";

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

  // Build cytoscape elements from config
  const buildElements = useCallback(() => {
    const elements: cytoscape.ElementDefinition[] = [];
    const createdGroups = new Set<string>();

    for (const node of config.nodes) {
      const group = String(
        node.group ?? node.properties?.group ?? node.properties?.group_name ?? "",
      ).trim();

      if (group) {
        const parentId = `group:${group}`;
        if (!createdGroups.has(parentId)) {
          createdGroups.add(parentId);
          elements.push({
            data: { id: parentId, label: group, isGroup: true },
          });
        }
      }

      const isStreamPoint =
        Boolean(node.properties?.stream_point) ||
        Boolean(node.metadata?.stream_point);

      // Build a human-readable label: "Torch Outlet" from "torch_outlet"
      const streamLabel = isStreamPoint
        ? node.id
            .replace(/_outlet$/, " Outlet")
            .split("_")
            .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
            .join(" ")
        : node.id;

      elements.push({
        data: {
          id: node.id,
          label: streamLabel,
          type: node.type,
          temperature: Number(node.properties?.temperature ?? 300),
          stream_point: isStreamPoint || undefined,
          ...(group ? { parent: `group:${group}` } : {}),
        },
      });
    }

    for (const conn of config.connections) {
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
        // Reactor nodes (non-Reservoir, non-group) render as round-rectangle to
        // distinguish them from boundary nodes (octagon) and stream points (diamond).
        selector: "node:not([isGroup]):not([type = 'Reservoir'])",
        style: { shape: "round-rectangle" },
      },
      {
        selector: "[type = 'Reservoir']",
        style: { shape: "octagon" },
      },
      {
        // Stream-point reservoirs render as P&ID diamond nodes at stage boundaries.
        // Must follow [type = 'Reservoir'] to override its octagon shape.
        selector: "[stream_point = true]",
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
        // StreamConnector: display-only outlet edge from source reactor to
        // stream-point diamond.  No Cantera object; shown as a thin dashed
        // line with no label so it visually bridges the stage boundary without
        // implying a flow device.
        selector: "[type = 'StreamConnector']",
        style: {
          width: 1.5,
          "line-style": "dashed",
          "line-dash-pattern": [6, 4],
          "target-arrow-shape": "triangle",
          label: "",
          "line-color": isDark ? "#666" : "#bbb",
          "target-arrow-color": isDark ? "#666" : "#bbb",
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

  // Initialize cytoscape
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: buildElements(),
      style: buildStylesheet() as any,
      layout: {
        name: "dagre",
        rankDir: "LR",
        nodeSep: 120,
        rankSep: 200,
      } as any,
      minZoom: 0.3,
      maxZoom: 3,
      userPanningEnabled: true,
      userZoomingEnabled: true,
    });

    cy.on("tap", "node", (e: EventObject) => {
      const data = e.target.data();
      if (data.isGroup) return;
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

  // Update elements when config changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.json({ elements: buildElements() });
    const layout = cy.layout({
      name: "dagre",
      rankDir: "LR",
      nodeSep: 120,
      rankSep: 200,
      animate: true,
      animationDuration: 300,
    } as any);
    layout.run();
    layout.promiseOn("layoutstop").then(() => {
      nudgeOverlappingNodes(cy);
    });
  }, [buildElements, nudgeOverlappingNodes]);

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
      className="relative border border-border rounded-md overflow-hidden"
      style={{ height: graphHeight }}
    >
      <div
        ref={containerRef}
        id="reactor-graph"
        className="w-full h-full"
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
