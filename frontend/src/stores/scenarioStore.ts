import { create } from "zustand";
import {
  createScenario as apiCreateScenario,
  deleteScenario as apiDeleteScenario,
  fetchScenario,
  listScenarios,
  renameScenario as apiRenameScenario,
  updateScenario as apiUpdateScenario,
  type ScenarioMeta,
} from "@/api/scenarios";
import { useSimulationStore } from "./simulationStore";
import { useSelectionStore } from "./selectionStore";

interface ScenarioState {
  available: boolean;
  scenarios: ScenarioMeta[];
  /** Unix seconds the store was written; drives the "computed X ago" label. */
  createdAt?: number;
  activeId: string | null;
  loading: boolean;
  error: string | null;

  /** Fetch the scenario list for the active store (no-op-safe if none). */
  refresh: () => Promise<void>;
  /** Load a scenario's trajectory and push it into the simulation results. */
  setActive: (id: string) => Promise<void>;
  /**
   * Create a new scenario overlay (blank, or cloned from `baseId`) and mark
   * it active for editing. Throws on failure (id collision, no config file,
   * bad YAML) so callers can show the error inline.
   */
  createScenario: (id: string, baseId?: string) => Promise<void>;
  /** Save edits to a scenario overlay's YAML text. */
  updateScenario: (id: string, yaml: string) => Promise<void>;
  /** Rename a scenario's id. */
  renameScenario: (id: string, newId: string) => Promise<void>;
  /** Delete a scenario overlay. */
  deleteScenario: (id: string) => Promise<void>;
}

export const useScenarioStore = create<ScenarioState>((set, get) => ({
  available: false,
  scenarios: [],
  activeId: null,
  loading: false,
  error: null,

  refresh: async () => {
    try {
      const resp = await listScenarios();
      set({
        available: resp.available,
        scenarios: resp.scenarios ?? [],
        createdAt: resp.created_at ?? undefined,
      });
    } catch {
      // No store / API not ready: the pane simply stays hidden.
      set({ available: false, scenarios: [] });
    }
  },

  createScenario: async (id, baseId) => {
    await apiCreateScenario(id, baseId);
    set({ activeId: id });
    // The scenario config now exists but has no precomputed trajectory yet
    // (that needs a Run Sweep) — `available`/`scenarios` are left as-is until
    // the caller/editor decides whether to refresh the (still HDF5-backed) list.
  },

  updateScenario: async (id, yaml) => {
    await apiUpdateScenario(id, yaml);
  },

  renameScenario: async (id, newId) => {
    await apiRenameScenario(id, newId);
    if (get().activeId === id) set({ activeId: newId });
  },

  deleteScenario: async (id) => {
    await apiDeleteScenario(id);
    if (get().activeId === id) set({ activeId: null });
  },

  setActive: async (id) => {
    set({ loading: true, error: null, activeId: id });
    try {
      const result = await fetchScenario(id);
      // Same sink the cached-result path uses → swaps result data only, no
      // network rebuild (the graph topology is unchanged).
      useSimulationStore.getState().setResults(result);

      // Auto-select the reactor node so the Plots tab shows the trajectory
      // without the user having to click the (single) node first. Keep an
      // existing valid selection if the user already picked a real reactor.
      const series = result.reactors_series ?? {};
      const ids = Object.keys(series);
      const sel = useSelectionStore.getState();
      const current = sel.selectedElement;
      const currentValid =
        current?.type === "node" &&
        ids.includes(String((current.data as { id?: unknown }).id));
      if (ids.length > 0 && !currentValid) {
        sel.setSelectedElement({ type: "node", data: { id: ids[0] } });
      }
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      set({ loading: false });
    }
  },
}));
