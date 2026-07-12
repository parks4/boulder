import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useScenarioStore } from "@/stores/scenarioStore";
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
    createdAt,
    activeId,
    loading,
    error,
    refresh,
    setActive,
  } = useScenarioStore();

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

  if (!available || scenarios.length === 0) return null;

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
      <SweepResultsPlot scenarios={scenarios} />
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm text-foreground">Scenarios</h3>
        <span className="text-xs text-muted-foreground">{scenarios.length}</span>
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
            <li key={s.id}>
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
                  "w-full text-left rounded-md px-2 py-1.5 text-xs transition-colors border",
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
            </li>
          );
        })}
      </ul>
      </div>
    </div>
  );
}
