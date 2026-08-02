import { create } from "zustand";
import {
  BASELINE_SCENARIO_ID,
  clearScenarioCache as apiClearScenarioCache,
  createScenario as apiCreateScenario,
  deleteScenario as apiDeleteScenario,
  fetchScenario,
  fetchScenarioPreview,
  listScenarios,
  renameScenario as apiRenameScenario,
  updateScenario as apiUpdateScenario,
  type ScenarioMeta,
  type ScenarioOverlay,
} from "@/api/scenarios";
import type { ConfigConnection, ConfigNode } from "@/types/config";
import { useSimulationStore } from "./simulationStore";
import { useSelectionStore } from "./selectionStore";

function idsFromOverlays(overlays: Record<string, ScenarioOverlay>): string[] {
  const ids = Object.keys(overlays);
  return ids.length ? [BASELINE_SCENARIO_ID, ...ids] : [];
}

interface ScenarioState {
  available: boolean;
  scenarios: ScenarioMeta[];
  /** Every scenario id, computed or not -- derived from `overlays`. */
  authoredIds: string[];
  /**
   * This session's in-memory scenario overlays -- the sole source of truth
   * for scenario authoring now that it no longer touches disk. Seeded once
   * from the server's startup snapshot (the first `refresh()`) and mutated
   * locally from then on via `applyOverlays`; the only way any of this
   * reaches disk is the Scenario YAML pane's "Download full YAML" button.
   */
  overlays: Record<string, ScenarioOverlay>;
  overlaysSeeded: boolean;
  /** Unix seconds the store was written; drives the "computed X ago" label. */
  createdAt?: number;
  activeId: string | null;
  loading: boolean;
  error: string | null;
  /**
   * Bumped by every `refresh()`/`applyOverlays()` call — listen to this
   * instead of `scenarios`/`overlays` when you only care "did something
   * about the scenarios change", e.g. to re-fetch unrelated derived info.
   */
  revision: number;

  /**
   * Effective (base + overlay) node/connection properties for `previewId` —
   * lets the Inputs pane show a scenario's parameter overrides immediately,
   * even for an authored scenario Run Sweep hasn't solved yet. Populated by
   * every `setActive()` call, computed or not (see `loadPreview`).
   */
  previewId: string | null;
  previewNodes: ConfigNode[] | null;
  previewConnections: ConfigConnection[] | null;
  previewLoading: boolean;
  previewError: string | null;
  /** Internal: guards against a stale response landing after a newer selection. */
  previewSeq: number;

  /** Fetch the scenario list for the active store (no-op-safe if none). */
  refresh: () => Promise<void>;
  /** Load a scenario's trajectory and push it into the simulation results. */
  setActive: (id: string) => Promise<void>;
  /**
   * Fetch `id`'s effective node/connection properties (base ⊕ overlay) into
   * `previewNodes`/`previewConnections`, using this store's own current
   * overlay for `id`. Called by `setActive` for every selection, so callers
   * normally don't need to call this directly.
   */
  loadPreview: (id: string) => Promise<void>;
  /**
   * Apply a scenario-mutation response's overlays map — every mutator below
   * calls this. Exposed so a caller that mutates overlays directly through
   * the API (e.g. the Properties panel's per-entity save) can fold its
   * result back into this store without duplicating the bookkeeping.
   */
  applyOverlays: (overlays: Record<string, ScenarioOverlay>) => void;
  /**
   * Create a new scenario overlay (blank, or cloned from `baseId`) and mark
   * it active for editing. Throws on failure (id collision, bad base id) so
   * callers can show the error inline.
   */
  createScenario: (id: string, baseId?: string, description?: string) => Promise<void>;
  /** Apply edits to a scenario overlay's YAML text. */
  updateScenario: (id: string, yaml: string) => Promise<void>;
  /** Rename a scenario's id. */
  renameScenario: (id: string, newId: string) => Promise<void>;
  /** Delete a scenario overlay; resolves with whether a cached result was purged too. */
  deleteScenario: (id: string) => Promise<{ cachePurged: boolean }>;
  /** Clear every scenario's cached trajectory; resolves with whether there was a store to clear. */
  clearCache: () => Promise<{ cleared: boolean }>;
}

export const useScenarioStore = create<ScenarioState>((set, get) => ({
  available: false,
  scenarios: [],
  authoredIds: [],
  overlays: {},
  overlaysSeeded: false,
  activeId: null,
  loading: false,
  error: null,
  revision: 0,
  previewId: null,
  previewNodes: null,
  previewConnections: null,
  previewLoading: false,
  previewError: null,
  previewSeq: 0,

  refresh: async () => {
    try {
      const resp = await listScenarios();
      set((s) => {
        // The server's `authored_overlays` is its startup snapshot -- only
        // the seed for this store's own state, never applied again after
        // the first call, or every refresh would clobber local edits with
        // stale disk content.
        const overlays = s.overlaysSeeded ? s.overlays : resp.authored_overlays ?? {};
        return {
          available: resp.available,
          scenarios: resp.scenarios ?? [],
          overlays,
          overlaysSeeded: true,
          authoredIds: idsFromOverlays(overlays),
          createdAt: resp.created_at ?? undefined,
          revision: s.revision + 1,
        };
      });
    } catch {
      // No store / API not ready: the pane simply stays hidden.
      set((s) => ({
        available: false,
        scenarios: [],
        revision: s.revision + 1,
      }));
    }
  },

  applyOverlays: (overlays) => {
    set((s) => ({
      overlays,
      overlaysSeeded: true,
      authoredIds: idsFromOverlays(overlays),
      revision: s.revision + 1,
    }));
  },

  createScenario: async (id, baseId, description) => {
    const resp = await apiCreateScenario(get().overlays, id, baseId, description);
    get().applyOverlays(resp.overlays);
    set({ activeId: id });
  },

  updateScenario: async (id, yaml) => {
    const resp = await apiUpdateScenario(get().overlays, id, yaml);
    get().applyOverlays(resp.overlays);
  },

  renameScenario: async (id, newId) => {
    const resp = await apiRenameScenario(get().overlays, id, newId);
    get().applyOverlays(resp.overlays);
    if (get().activeId === id) set({ activeId: newId });
  },

  deleteScenario: async (id) => {
    const resp = await apiDeleteScenario(get().overlays, id);
    get().applyOverlays(resp.overlays);
    if (get().activeId === id) set({ activeId: null });
    if (get().previewId === id) {
      set({ previewId: null, previewNodes: null, previewConnections: null, previewError: null });
    }
    return { cachePurged: resp.cache_purged };
  },

  clearCache: async () => {
    const resp = await apiClearScenarioCache();
    set({ activeId: null });
    await get().refresh();
    return { cleared: resp.cleared };
  },

  setActive: async (id) => {
    set({ activeId: id, error: null });
    // Always preview the scenario's effective properties, computed or not —
    // this is what lets the Inputs pane show an authored-but-unswept
    // scenario's overrides without ever needing a trajectory.
    void get().loadPreview(id);

    // Not computed yet (authored but unswept, or mid-sweep and not reached/
    // finished yet) — just record the selection, no fetch. `GET /api/scenarios/
    // {id}` would 404 for it; the Scenario Pane / results area read `activeId`
    // directly to show a "calculating"/"pending" state for this case instead.
    // Clear any previous scenario's results too, or ReactorGraph keeps
    // painting the flowsheet with the last-fetched scenario's stale status.
    if (!get().scenarios.some((s) => s.id === id)) {
      useSimulationStore.getState().clearResults();
      return;
    }
    set({ loading: true });
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

  loadPreview: async (id) => {
    const seq = get().previewSeq + 1;
    set({ previewSeq: seq, previewLoading: true, previewError: null });
    const overlay = id === BASELINE_SCENARIO_ID ? {} : get().overlays[id] ?? {};
    try {
      const preview = await fetchScenarioPreview(id, overlay);
      if (get().previewSeq !== seq) return; // superseded by a newer selection
      set({
        previewId: id,
        previewNodes: preview.nodes,
        previewConnections: preview.connections,
        previewLoading: false,
      });
    } catch (e) {
      if (get().previewSeq !== seq) return;
      set({
        previewError: e instanceof Error ? e.message : String(e),
        previewLoading: false,
      });
    }
  },
}));
