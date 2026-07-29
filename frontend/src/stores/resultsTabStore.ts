import { create } from "zustand";

interface ResultsTabState {
  /** null = no explicit choice: Plots while streaming; Sankey or Plots once results exist. */
  activeTab: string | null;
  setActiveTab: (tab: string) => void;
}

export const useResultsTabStore = create<ResultsTabState>((set) => ({
  activeTab: null,
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
