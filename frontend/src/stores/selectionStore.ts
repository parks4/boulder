import { create } from "zustand";

export interface SelectedElement {
  type: "node" | "edge";
  data: Record<string, unknown>;
}

export interface SetSelectedElementOptions {
  editInitialConditions?: boolean;
}

interface SelectionState {
  selectedElement: SelectedElement | null;
  /** Incremented when a graph double-click requests initial-conditions edit. */
  initialConditionsEditNonce: number;
  setSelectedElement: (
    element: SelectedElement | null,
    options?: SetSelectedElementOptions,
  ) => void;
  clearSelection: () => void;
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedElement: null,
  initialConditionsEditNonce: 0,
  setSelectedElement: (element, options) =>
    set((state) => ({
      selectedElement: element,
      initialConditionsEditNonce: options?.editInitialConditions
        ? state.initialConditionsEditNonce + 1
        : state.initialConditionsEditNonce,
    })),
  clearSelection: () => set({ selectedElement: null }),
}));
