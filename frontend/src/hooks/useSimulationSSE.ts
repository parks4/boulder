import { useEffect, useRef } from "react";
import { useSimulationStore } from "@/stores/simulationStore";
import type { SimulationProgress, SimulationResults } from "@/types/simulation";

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
