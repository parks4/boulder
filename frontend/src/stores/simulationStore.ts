import { create } from "zustand";
import type { SimulationProgress, SimulationResults } from "@/types/simulation";

interface SimulationState {
  isRunning: boolean;
  simulationId: string | null;
  progress: SimulationProgress | null;
  results: SimulationResults | null;
  /**
   * Cache fingerprint of `results`, known only when they were served from the
   * result cache (the cache check answers with it). A fresh solve's completion
   * event carries none, so this is null then.
   */
  fingerprint: string | null;
  pythonCode: string;
  error: string | null;

  // Actions
  /** Set running=true immediately (before the POST returns) so the overlay shows at once. */
  beginSimulationRun: () => void;
  startSimulation: (simulationId: string) => void;
  updateProgress: (progress: SimulationProgress) => void;
  setResults: (results: SimulationResults, fingerprint?: string) => void;
  setError: (error: string) => void;
  /** The SSE stream's terminal "stopped" event: the solve thread has exited
   * after a stop request, with no completion and no error. */
  stopped: () => void;
  clearResults: () => void;
  setPythonCode: (code: string) => void;
}

export const useSimulationStore = create<SimulationState>((set) => ({
  isRunning: false,
  simulationId: null,
  progress: null,
  results: null,
  fingerprint: null,
  pythonCode: "",
  error: null,

  beginSimulationRun: () =>
    set({
      isRunning: true,
      simulationId: null,
      progress: null,
      results: null,
      fingerprint: null,
      pythonCode: "",
      error: null,
    }),

  startSimulation: (simulationId) =>
    set({
      isRunning: true,
      simulationId,
      progress: null,
      results: null,
      fingerprint: null,
      pythonCode: "",
      error: null,
    }),

  updateProgress: (progress) => set({ progress }),

  setResults: (results, fingerprint) =>
    set({
      isRunning: false,
      results,
      fingerprint: fingerprint ?? null,
      pythonCode: results.code_str ?? "",
    }),

  setError: (error) => set({ isRunning: false, error }),

  stopped: () => set({ isRunning: false }),

  clearResults: () =>
    set({
      isRunning: false,
      simulationId: null,
      progress: null,
      results: null,
      fingerprint: null,
      pythonCode: "",
      error: null,
    }),

  setPythonCode: (code) => set({ pythonCode: code }),
}));
