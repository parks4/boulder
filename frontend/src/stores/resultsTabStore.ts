import { create } from "zustand";

interface ResultsTabState {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const useResultsTabStore = create<ResultsTabState>((set) => ({
  activeTab: "Plots",
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
