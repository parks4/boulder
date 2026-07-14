import { create } from "zustand";

interface SolverDetailsState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

/**
 * Whether the Solver Details modal is open.
 *
 * The modal itself (and the solver field state it edits) stays owned by
 * SimulateCard, but the Stage panel also needs to open it — hence a tiny
 * shared store instead of local component state.
 */
export const useSolverDetailsStore = create<SolverDetailsState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));
