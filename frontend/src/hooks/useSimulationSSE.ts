import { useEffect, useRef } from "react";
import { useSimulationStore } from "@/stores/simulationStore";
import { useConfigStore } from "@/stores/configStore";
import type { SimulationProgress, SimulationResults } from "@/types/simulation";
// useConfigStore is accessed via .getState() inside callbacks to avoid stale closures.

/**
 * Hook that connects to the simulation SSE stream and updates the store.
 * Automatically cleans up when the component unmounts or the simulation ID changes.
 */
export function useSimulationSSE() {
  const sourceRef = useRef<EventSource | null>(null);
  const { simulationId, isRunning, updateProgress, setResults, setError } =
    useSimulationStore();

  useEffect(() => {
    if (!simulationId || !isRunning) return;

    const url = `/api/simulations/${simulationId}/stream`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.addEventListener("progress", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SimulationProgress;
        updateProgress(data);
      } catch {
        /* ignore parse errors */
      }
    });

    source.addEventListener("complete", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SimulationResults;
        setResults(data);

        // Single source of truth: atomically replace nodes + connections with the
        // authoritative post-build lists from the backend.  Both lists are always
        // sent together; we require both to avoid leaving the graph half-updated.
        //
        // Frontend-only metadata keys (e.g. layout_offset set by the user dragging
        // nodes) are NOT known to the backend and are absent from updated_nodes.
        // Carry them forward from the current config so dragged positions survive
        // the simulation update.
        if (data.updated_nodes != null && data.updated_connections != null) {
          const { config: currentConfig, setConfig } = useConfigStore.getState();
          // Build a lookup map: nodeId → frontend-only metadata to preserve.
          // Currently only layout_offset is considered frontend-only; expand as needed.
          const frontendMeta = new Map<string, Record<string, unknown>>();
          for (const n of currentConfig.nodes) {
            const off = (n.metadata as Record<string, unknown> | null)?.layout_offset;
            if (off !== undefined) frontendMeta.set(n.id, { layout_offset: off });
          }
          setConfig({
            ...currentConfig,
            nodes: data.updated_nodes.map((n) => {
              const extra = frontendMeta.get(n.id);
              return {
                id: n.id,
                type: n.type,
                group: n.group ?? null,
                properties: n.properties ?? {},
                metadata: extra
                  ? { ...(n.metadata ?? {}), ...extra }
                  : (n.metadata ?? null),
              };
            }),
            connections: data.updated_connections.map((c) => ({
              id: c.id,
              source: c.source,
              target: c.target,
              type: c.type,
              properties: c.properties ?? {},
              metadata: c.metadata ?? null,
              // group and logical must be preserved so that convert_to_stone_format
              // can route each connection to the correct stage block when the user
              // opens the YAML editor.  Without group, all connections are silently
              // dropped from the merged YAML.
              group: c.group ?? null,
              logical: c.logical ?? null,
            })),
          });
        }
      } catch {
        /* ignore parse errors */
      }
      source.close();
    });

    source.addEventListener("error", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setError(data.message ?? "Simulation failed");
      } catch {
        setError("Connection to simulation lost");
      }
      source.close();
    });

    source.onerror = () => {
      // EventSource connection error – simulation may have ended
      source.close();
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [simulationId, isRunning, updateProgress, setResults, setError]);
}
