import { create } from "zustand";

/** Persisted left/right sidebar collapse state and widths (Claude-desktop style). */
const STORAGE_KEY = "boulder-layout";
const LEFT_DEFAULT = 320;
const RIGHT_DEFAULT = 250;
const YAML_DEFAULT = 420;
const MIN_WIDTH = 180;
const MAX_WIDTH = 600;
const YAML_MAX_WIDTH = 900;

interface LayoutState {
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  leftWidth: number;
  rightWidth: number;
  toggleLeft: () => void;
  toggleRight: () => void;
  setLeftWidth: (w: number) => void;
  setRightWidth: (w: number) => void;
  /** The YAML editor pane (opened on demand from Network's "Edit YAML"), not persisted open/closed. */
  yamlPaneOpen: boolean;
  yamlWidth: number;
  openYamlPane: () => void;
  closeYamlPane: () => void;
  setYamlWidth: (w: number) => void;
}

function clampWidth(w: number, max: number = MAX_WIDTH): number {
  return Math.max(MIN_WIDTH, Math.min(max, Math.round(w)));
}

function load(): Partial<LayoutState> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function save(patch: Partial<LayoutState>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...load(), ...patch }));
  } catch {
    /* ignore quota / disabled storage */
  }
}

export const useLayoutStore = create<LayoutState>((set) => {
  const init = load();
  return {
    leftCollapsed: Boolean(init.leftCollapsed),
    rightCollapsed: Boolean(init.rightCollapsed),
    leftWidth: clampWidth(init.leftWidth ?? LEFT_DEFAULT),
    rightWidth: clampWidth(init.rightWidth ?? RIGHT_DEFAULT),
    yamlPaneOpen: false,
    yamlWidth: clampWidth(init.yamlWidth ?? YAML_DEFAULT, YAML_MAX_WIDTH),

    toggleLeft: () =>
      set((s) => {
        const leftCollapsed = !s.leftCollapsed;
        save({ leftCollapsed });
        return { leftCollapsed };
      }),
    toggleRight: () =>
      set((s) => {
        const rightCollapsed = !s.rightCollapsed;
        save({ rightCollapsed });
        return { rightCollapsed };
      }),
    setLeftWidth: (w) => {
      const leftWidth = clampWidth(w);
      save({ leftWidth });
      set({ leftWidth });
    },
    setRightWidth: (w) => {
      const rightWidth = clampWidth(w);
      save({ rightWidth });
      set({ rightWidth });
    },
    openYamlPane: () => set({ yamlPaneOpen: true }),
    closeYamlPane: () => set({ yamlPaneOpen: false }),
    setYamlWidth: (w) => {
      const yamlWidth = clampWidth(w, YAML_MAX_WIDTH);
      save({ yamlWidth });
      set({ yamlWidth });
    },
  };
});
