import { create } from "zustand";

interface ReactorModalState {
  open: boolean;
  group?: string | null;
}

interface ConnectionModalState {
  open: boolean;
  group?: string | null;
  source?: string;
}

interface AddEntityModalState {
  reactorModal: ReactorModalState;
  connectionModal: ConnectionModalState;
  openAddReactor: (opts?: { group?: string | null }) => void;
  openAddConnection: (opts?: { group?: string | null; source?: string }) => void;
  closeAddReactor: () => void;
  closeAddConnection: () => void;
}

/**
 * Shared trigger state for the Add Reactor / Add Connection modals.
 *
 * The modals are rendered once, at the app shell level, but opened from
 * several places that don't otherwise share state: the Stage panel's
 * "+ Add Reactor"/"+ Add Connection" buttons and right-click on the
 * Cytoscape canvas (background = add reactor, node = add connection from
 * that node). A store lets any of them open the same modal instance
 * pre-filled with the right stage/source.
 */
export const useAddEntityModalStore = create<AddEntityModalState>((set) => ({
  reactorModal: { open: false },
  connectionModal: { open: false },
  openAddReactor: (opts) => set({ reactorModal: { open: true, group: opts?.group } }),
  openAddConnection: (opts) =>
    set({
      connectionModal: { open: true, group: opts?.group, source: opts?.source },
    }),
  closeAddReactor: () => set({ reactorModal: { open: false } }),
  closeAddConnection: () => set({ connectionModal: { open: false } }),
}));
