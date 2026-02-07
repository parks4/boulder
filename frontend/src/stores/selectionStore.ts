import { create } from "zustand";

export interface SelectedElement {
  type: "node" | "edge";
  data: Record<string, unknown>;
}

interface SelectionState {
  selectedElement: SelectedElement | null;
  setSelectedElement: (element: SelectedElement | null) => void;
  clearSelection: () => void;
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedElement: null,
  setSelectedElement: (element) => set({ selectedElement: element }),
  clearSelection: () => set({ selectedElement: null }),
}));
