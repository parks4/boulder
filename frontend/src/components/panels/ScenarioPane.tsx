import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Ban, Eraser, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useSweepRunStore } from "@/stores/sweepStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { AddScenarioModal } from "@/components/modals/AddScenarioModal";
import { SweepResultsPlot } from "./SweepResultsPlot";
import { BASELINE_SCENARIO_ID, type ScenarioMeta } from "@/api/scenarios";

/** One row in the pane: every authored id, paired with its computed data if any. */
interface ScenarioRow {
  id: string;
  computed: ScenarioMeta | null;
}

/** `authoredIds` first (the sweep's solve order), then any computed scenario
 * a host's `run_sweep.py` produced without declaring it in `scenarios:`. */
function buildRows(authoredIds: string[], scenarios: ScenarioMeta[]): ScenarioRow[] {
  const byId = new Map(scenarios.map((s) => [s.id, s]));
  const seen = new Set<string>();
  const rows: ScenarioRow[] = authoredIds.map((id) => {
    seen.add(id);
    return { id, computed: byId.get(id) ?? null };
  });
  for (const s of scenarios) {
    if (!seen.has(s.id)) rows.push({ id: s.id, computed: s });
  }
  return rows;
}

/** Compact relative-time label, e.g. "just now", "2 min ago", "3 h ago". */
function timeAgo(tsSeconds: number | undefined, nowMs: number): string {
  if (!tsSeconds) return "";
  const s = Math.max(0, nowMs / 1000 - tsSeconds);
  if (s < 45) return "just now";
  if (s < 90) return "1 min ago";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 5400) return "1 h ago";
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/**
 * Right-side pane listing precomputed scenarios from the active HDF5 store.
 * Selecting one loads its trajectory (no network rebuild). Supports up/down
 * arrow navigation, shows when each scenario was computed, and bumps when the
 * list is (re)computed by a sweep. Renders nothing when no store is available.
 */
export function ScenarioPane() {
  const {
    scenarios,
    authoredIds,
    createdAt,
    units,
    nonKpiKeys,
    activeId,
    loading,
    error,
    refresh,
    setActive,
    deleteScenario,
    clearCache,
    clearEntryCache,
  } = useScenarioStore();
  const scenarioProgress = useSweepRunStore((s) => s.scenarioProgress);
  const openYamlPane = useLayoutStore((s) => s.openYamlPane);
  const openScenarioYamlEditor = useLayoutStore((s) => s.openScenarioYamlEditor);
  const [addModalOpen, setAddModalOpen] = useState(false);

  /** BASELINE is the unmodified base config, not an authored overlay -- edit
   * it via the full YAML pane instead of the scoped (and otherwise 404ing)
   * scenario overlay editor. */
  const handleEditRow = (id: string) => {
    if (id === BASELINE_SCENARIO_ID) openYamlPane();
    else openScenarioYamlEditor(id);
  };

  // Tick so relative-time labels stay fresh without a reload.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // One-shot bump when a sweep (re)computes the store (createdAt changes).
  const [bump, setBump] = useState(false);
  const prevCreated = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (createdAt === undefined) return;
    if (prevCreated.current !== undefined && createdAt !== prevCreated.current) {
      setBump(true);
      setNow(Date.now());
      const t = setTimeout(() => setBump(false), 900);
      prevCreated.current = createdAt;
      return () => clearTimeout(t);
    }
    prevCreated.current = createdAt;
  }, [createdAt]);

  const handleDelete = async (id: string, isComputed: boolean) => {
    // Only a computed row actually has a cached trajectory to lose.
    const confirmMsg = isComputed
      ? `Delete scenario "${id}"? This also removes its cached trajectory ` +
        "immediately. This cannot be undone."
      : `Delete scenario "${id}"? This cannot be undone.`;
    if (!window.confirm(confirmMsg)) return;
    try {
      const { cachePurged } = await deleteScenario(id);
      toast.success(
        cachePurged
          ? `Scenario "${id}" and its cached result deleted`
          : `Scenario "${id}" deleted`,
      );
    } catch (err) {
      toast.error(
        `Could not delete scenario: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  const handleClearRowCache = async (id: string) => {
    if (
      !window.confirm(
        `Clear the cached result for "${id}"? Its definition is untouched — ` +
          "Run Sweep will recompute it next time.",
      )
    ) {
      return;
    }
    try {
      const { cleared } = await clearEntryCache(id);
      toast.success(
        cleared ? `Cached result for "${id}" cleared` : `No cached result for "${id}"`,
      );
    } catch (err) {
      toast.error(
        `Could not clear cache: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  const handleClearCache = async () => {
    if (
      !window.confirm(
        `Clear the cached results for all ${scenarios.length} scenario(s)? ` +
          "This does not touch their definitions — Run Sweep will recompute " +
          "them from scratch next time.",
      )
    ) {
      return;
    }
    try {
      const { cleared } = await clearCache();
      toast.success(cleared ? "Scenario cache cleared" : "No cache to clear");
    } catch (err) {
      toast.error(
        `Could not clear cache: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  if (authoredIds.length === 0 && scenarios.length === 0) {
    // Nothing authored, nothing computed — scenario authoring doesn't need a
    // store, so surface just the "+ Add Scenario" entry point (Run Sweep's
    // menu has it too).
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm text-foreground">Scenarios</h3>
          <button
            type="button"
            onClick={() => setAddModalOpen(true)}
            className="flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <Plus size={12} /> Add Scenario
          </button>
        </div>
        <p className="text-xs text-muted-foreground">
          No computed scenarios yet — add one, then Run Sweep.
        </p>
        <AddScenarioModal
          open={addModalOpen}
          onClose={() => setAddModalOpen(false)}
          onCreated={(id) => openScenarioYamlEditor(id)}
        />
      </div>
    );
  }

  // Every authored id (Run Sweep's solve order), paired with its computed
  // data if any — kept as one list so a scenario mid-sweep (or never yet
  // swept) stays visible and clickable instead of disappearing once
  // something else has been computed.
  const rows = buildRows(authoredIds, scenarios);

  const onKeyDown = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const idx = rows.findIndex((r) => r.id === activeId);
    let next =
      idx === -1
        ? e.key === "ArrowDown"
          ? 0
          : rows.length - 1
        : e.key === "ArrowDown"
          ? idx + 1
          : idx - 1;
    next = Math.max(0, Math.min(rows.length - 1, next));
    const target = rows[next];
    if (!target) return;
    void setActive(target.id);
    // Focus synchronously on the already-rendered node — a requestAnimationFrame
    // here loses the race against the post-load re-render, leaving the focus ring
    // stuck on the previous row while the active highlight moves.
    const el = document.getElementById(`scenario-${target.id}`);
    el?.focus();
    el?.scrollIntoView({ block: "nearest" });
  };

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm text-foreground">Scenarios</h3>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{rows.length}</span>
            {scenarios.length > 0 && (
              <button
                type="button"
                onClick={() => void handleClearCache()}
                title="Clear cache (delete every scenario's cached result, without re-solving)"
                className="text-muted-foreground hover:text-foreground"
              >
                <Eraser size={14} />
              </button>
            )}
            <button
              type="button"
              onClick={() => setAddModalOpen(true)}
              title="Add Scenario"
              className="text-muted-foreground hover:text-foreground"
            >
              <Plus size={14} />
            </button>
          </div>
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
        {scenarios.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Not computed yet — Run Sweep to solve{" "}
            {rows.length === 1 ? "it" : "them"}.
          </p>
        )}
        <ul
          onKeyDown={onKeyDown}
          className={`space-y-1 max-h-[70vh] overflow-y-auto pr-1${
            bump ? " animate-[scenarioBump_0.6s_ease-out]" : ""
          }`}
        >
          {rows.map((row) => {
            const isActive = row.id === activeId;
            const isCalculating = row.id in scenarioProgress;
            const s = row.computed;
            const ago = s ? timeAgo(s.computed_at ?? createdAt, now) : "";
            return (
              // The action icons are an overlay (below), not siblings in a
              // flex row: as siblings they permanently reserved an icon column
              // even while hidden, so no row ever reached the pane's full
              // width. They now sit on top of the status label instead, which
              // fades out on hover.
              <li key={row.id} className="group relative">
                <button
                  id={`scenario-${row.id}`}
                  type="button"
                  onClick={() => void setActive(row.id)}
                  aria-busy={loading && isActive}
                  title={
                    s?.final_temperature_K != null
                      ? `T_final ≈ ${Math.round(s.final_temperature_K)} K` +
                        (s.solid_carbon_yield_pct != null
                          ? ` · C(s) ${s.solid_carbon_yield_pct.toFixed(1)}%`
                          : "")
                      : undefined
                  }
                  className={[
                    "w-full min-w-0 text-left rounded-md px-2 py-1.5 text-xs transition-colors border",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400",
                    isActive
                      ? "border-blue-500 bg-blue-500/20 text-foreground"
                      : "border-transparent hover:bg-muted text-foreground",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium truncate">{row.id}</span>
                    {/* Hidden on hover -- the action icons take this spot. */}
                    {isCalculating ? (
                      <span className="shrink-0 text-[10px] text-primary animate-pulse group-hover:opacity-0">
                        Calculating…
                      </span>
                    ) : s ? (
                      ago && (
                        <span className="shrink-0 text-[10px] text-muted-foreground group-hover:opacity-0">
                          {ago}
                        </span>
                      )
                    ) : (
                      <span className="shrink-0 text-[10px] text-muted-foreground group-hover:opacity-0">
                        Not computed yet
                      </span>
                    )}
                  </div>
                  {/* Descriptive scenario_name, when it adds anything beyond
                      the id -- often identical/inherited across scenarios,
                      which made every row look the same (the id, always
                      unique, is the primary label above). */}
                  {s?.label && s.label !== row.id && (
                    <div className="text-[10px] text-muted-foreground truncate">
                      {s.label}
                    </div>
                  )}
                  {s?.reactor_mode && (
                    <div className="text-[10px] text-muted-foreground">
                      {s.reactor_mode}
                    </div>
                  )}
                </button>
                {/* `pointer-events-none` while hidden: the overlay covers part
                    of the row button, so without it an invisible icon would
                    swallow clicks meant to select the scenario. */}
                <div className="absolute right-1 top-1 flex items-center gap-0.5 opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto">
                  <button
                    type="button"
                    onClick={() => handleEditRow(row.id)}
                    title={
                      row.id === BASELINE_SCENARIO_ID
                        ? "Edit YAML (the base config BASELINE runs unmodified)"
                        : "Edit scenario YAML"
                    }
                    className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted"
                  >
                    <Pencil size={12} />
                  </button>
                  {/* Only a computed row has a cached trajectory to drop. */}
                  {s && (
                    <button
                      type="button"
                      onClick={() => void handleClearRowCache(row.id)}
                      title="Clear this scenario's cached result (keeps its definition)"
                      className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted"
                    >
                      <Eraser size={12} />
                    </button>
                  )}
                  {row.id === BASELINE_SCENARIO_ID ? (
                    // Same slot as the delete button below (kept present, not
                    // removed, so every row's icon column stays aligned) --
                    // BASELINE has no overlay of its own to delete.
                    <span
                      title="BASELINE cannot be deleted (it's the base config's own unmodified run, not an authored scenario)"
                      className="p-1 rounded text-muted-foreground cursor-not-allowed"
                    >
                      <Ban size={12} />
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void handleDelete(row.id, s !== null)}
                      title="Delete scenario"
                      className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-muted"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      <SweepResultsPlot
        scenarios={scenarios}
        units={units}
        nonKpiKeys={nonKpiKeys}
      />
      <AddScenarioModal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        onCreated={(id) => openScenarioYamlEditor(id)}
      />
    </div>
  );
}
