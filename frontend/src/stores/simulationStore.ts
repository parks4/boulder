import { create } from "zustand";
import type { SimulationProgress, SimulationResults } from "@/types/simulation";

interface SimulationState {
  isRunning: boolean;
  simulationId: string | null;
  progress: SimulationProgress | null;
  results: SimulationResults | null;
  pythonCode: string;
  error: string | null;

  // Actions
  startSimulation: (simulationId: string) => void;
  updateProgress: (progress: SimulationProgress) => void;
  setResults: (results: SimulationResults) => void;
  setError: (error: string) => void;
  clearResults: () => void;
  setPythonCode: (code: string) => void;
}

export const useSimulationStore = create<SimulationState>((set) => ({
  isRunning: false,
  simulationId: null,
  progress: null,
  results: null,
  pythonCode: "",
  error: null,

  startSimulation: (simulationId) =>
    set({
      isRunning: true,
      simulationId,
      progress: null,
      results: null,
      pythonCode: "",
      error: null,
    }),

  updateProgress: (progress) => set({ progress }),

  setResults: (results) =>
    set({
      isRunning: false,
      results,
      pythonCode: results.code_str ?? "",
    }),

  setError: (error) => set({ isRunning: false, error }),

  clearResults: () =>
    set({
      isRunning: false,
      simulationId: null,
      progress: null,
      results: null,
      pythonCode: "",
      error: null,
    }),

  setPythonCode: (code) => set({ pythonCode: code }),
}));
