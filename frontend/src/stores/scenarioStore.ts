import { create } from "zustand";
import {
  fetchScenario,
  listScenarios,
  type ScenarioMeta,
} from "@/api/scenarios";
import { useSimulationStore } from "./simulationStore";
import { useSelectionStore } from "./selectionStore";

interface ScenarioState {
  available: boolean;
  scenarios: ScenarioMeta[];
  activeId: string | null;
  loading: boolean;
  error: string | null;

  /** Fetch the scenario list for the active store (no-op-safe if none). */
  refresh: () => Promise<void>;
  /** Load a scenario's trajectory and push it into the simulation results. */
  setActive: (id: string) => Promise<void>;
}

export const useScenarioStore = create<ScenarioState>((set) => ({
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
      });
    } catch {
      // No store / API not ready: the pane simply stays hidden.
      set({ available: false, scenarios: [] });
    }
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
