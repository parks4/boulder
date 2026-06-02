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
        if (data.updated_nodes != null && data.updated_connections != null) {
          const { config: currentConfig, setConfig } = useConfigStore.getState();
          setConfig({
            ...currentConfig,
            nodes: data.updated_nodes.map((n) => ({
              id: n.id,
              type: n.type,
              group: n.group ?? null,
              properties: n.properties ?? {},
              metadata: n.metadata ?? null,
            })),
            connections: data.updated_connections.map((c) => ({
              id: c.id,
              source: c.source,
              target: c.target,
              type: c.type,
              properties: c.properties ?? {},
              metadata: c.metadata ?? null,
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
