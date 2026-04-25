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

        // Sync programmatically-created connections back into the visual graph.
        // Post-build hooks may add edges (e.g. tube_furnace → outlet) that were
        // not declared in the YAML; merge any that are not yet in the config.
        // Read fresh state via getState() to avoid a stale closure.
        if (data.updated_connections) {
          const { config: currentConfig, addConnection } =
            useConfigStore.getState();
          const existingIds = new Set(
            currentConfig.connections.map((c) => c.id),
          );
          for (const conn of data.updated_connections) {
            if (!existingIds.has(conn.id)) {
              addConnection({
                id: conn.id,
                source: conn.source,
                target: conn.target,
                type: conn.type,
                properties: conn.properties ?? {},
              });
            }
          }
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
