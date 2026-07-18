import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useSweepRunStore } from "@/stores/sweepStore";
import { AddScenarioModal } from "@/components/modals/AddScenarioModal";
import { ScenarioYamlEditorModal } from "@/components/modals/ScenarioYamlEditorModal";
import { SweepResultsPlot } from "./SweepResultsPlot";

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
    available,
    scenarios,
    authoredIds,
    createdAt,
    activeId,
    loading,
    error,
    refresh,
    setActive,
    deleteScenario,
  } = useScenarioStore();
  const sweeping = useSweepRunStore((s) => s.sweeping);
  const runSweepJob = useSweepRunStore((s) => s.run);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

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

  const handleDelete = async (id: string) => {
    // Every row here already has a cached trajectory (that's why it's in
    // `scenarios`, the store-derived list), so this message is always
    // accurate — deleting drops both the definition and its cached result.
    if (
      !window.confirm(
        `Delete scenario "${id}"? This also removes its cached trajectory ` +
          "immediately. This cannot be undone.",
      )
    ) {
      return;
    }
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

  const handleRegenerate = () => {
    if (
      !window.confirm(
        "Regenerate the cache? This re-solves every scenario in this sweep " +
          "from scratch, ignoring cached results. This may take a while.",
      )
    ) {
      return;
    }
    runSweepJob({ total: scenarios.length, noCache: true });
  };

  if (!available || scenarios.length === 0) {
    // No precomputed store yet (nothing has been swept), but scenario
    // authoring doesn't need one — surface just the "+ Add Scenario" entry
    // point so the pane isn't the only way in (Run Sweep's menu has it too).
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
        {authoredIds.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No computed scenarios yet — add one, then Run Sweep.
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              Not computed yet — Run Sweep to solve{" "}
              {authoredIds.length === 1 ? "it" : "them"}.
            </p>
            <ul className="space-y-1 max-h-[70vh] overflow-y-auto pr-1">
              {authoredIds.map((id) => (
                <li key={id} className="group flex items-center gap-1">
                  <span className="flex-1 min-w-0 truncate rounded-md px-2 py-1.5 text-xs text-foreground">
                    {id}
                  </span>
                  <button
                    type="button"
                    onClick={() => setEditingId(id)}
                    title="Edit scenario YAML"
                    className="shrink-0 p-1 rounded text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground hover:bg-muted"
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(id)}
                    title="Delete scenario"
                    className="shrink-0 p-1 rounded text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive hover:bg-muted"
                  >
                    <Trash2 size={12} />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
        <AddScenarioModal
          open={addModalOpen}
          onClose={() => setAddModalOpen(false)}
          onCreated={(id) => setEditingId(id)}
        />
        <ScenarioYamlEditorModal
          scenarioId={editingId}
          onClose={() => setEditingId(null)}
          onSaved={() => void refresh()}
        />
      </div>
    );
  }

  const onKeyDown = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const idx = scenarios.findIndex((s) => s.id === activeId);
    let next =
      idx === -1
        ? e.key === "ArrowDown"
          ? 0
          : scenarios.length - 1
        : e.key === "ArrowDown"
          ? idx + 1
          : idx - 1;
    next = Math.max(0, Math.min(scenarios.length - 1, next));
    const target = scenarios[next];
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
            <span className="text-xs text-muted-foreground">{scenarios.length}</span>
            <button
              type="button"
              onClick={handleRegenerate}
              disabled={sweeping}
              title="Regenerate cache (re-solve every scenario, ignoring cached results)"
              className="text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw size={14} className={sweeping ? "animate-spin" : ""} />
            </button>
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
        <ul
          onKeyDown={onKeyDown}
          className={`space-y-1 max-h-[70vh] overflow-y-auto pr-1${
            bump ? " animate-[scenarioBump_0.6s_ease-out]" : ""
          }`}
        >
          {scenarios.map((s) => {
            const isActive = s.id === activeId;
            const ago = timeAgo(s.computed_at ?? createdAt, now);
            return (
              <li key={s.id} className="group flex items-center gap-1">
                <button
                  id={`scenario-${s.id}`}
                  type="button"
                  onClick={() => void setActive(s.id)}
                  aria-busy={loading && isActive}
                  title={
                    s.final_temperature_K != null
                      ? `T_final ≈ ${Math.round(s.final_temperature_K)} K` +
                        (s.solid_carbon_yield_pct != null
                          ? ` · C(s) ${s.solid_carbon_yield_pct.toFixed(1)}%`
                          : "")
                      : undefined
                  }
                  className={[
                    "flex-1 min-w-0 text-left rounded-md px-2 py-1.5 text-xs transition-colors border",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400",
                    isActive
                      ? "border-blue-500 bg-blue-500/20 text-foreground"
                      : "border-transparent hover:bg-muted text-foreground",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium truncate">{s.label}</span>
                    {ago && (
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        {ago}
                      </span>
                    )}
                  </div>
                  {s.reactor_mode && (
                    <div className="text-[10px] text-muted-foreground">
                      {s.reactor_mode}
                    </div>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setEditingId(s.id)}
                  title="Edit scenario YAML"
                  className="shrink-0 p-1 rounded text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground hover:bg-muted"
                >
                  <Pencil size={12} />
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete(s.id)}
                  title="Delete scenario"
                  className="shrink-0 p-1 rounded text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive hover:bg-muted"
                >
                  <Trash2 size={12} />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      <SweepResultsPlot scenarios={scenarios} />
      <AddScenarioModal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        onCreated={(id) => setEditingId(id)}
      />
      <ScenarioYamlEditorModal
        scenarioId={editingId}
        onClose={() => setEditingId(null)}
        onSaved={() => void refresh()}
      />
    </div>
  );
}
