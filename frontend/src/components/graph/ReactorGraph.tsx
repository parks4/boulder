import { useEffect, useRef, useCallback } from "react";
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

  // Build cytoscape elements from config
  const buildElements = useCallback(() => {
    const elements: cytoscape.ElementDefinition[] = [];
    const createdGroups = new Set<string>();

    for (const node of config.nodes) {
      const group = String(
        node.properties?.group ?? node.properties?.group_name ?? "",
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

      elements.push({
        data: {
          id: node.id,
          label: node.id,
          type: node.type,
          temperature: Number(node.properties?.temperature ?? 300),
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
        selector: "[type = 'Reservoir']",
        style: { shape: "octagon" },
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

  return (
    <div
      id="graph-container"
      className="relative border border-border rounded-md overflow-hidden"
      style={{ minHeight: 360 }}
    >
      <div
        ref={containerRef}
        id="reactor-graph"
        className="w-full"
        style={{ height: 360, background: "var(--color-cytoscape-bg)" }}
        data-cy="graph"
      />
    </div>
  );
}
