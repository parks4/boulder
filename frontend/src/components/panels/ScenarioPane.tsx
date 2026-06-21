import { useEffect } from "react";
import { useScenarioStore } from "@/stores/scenarioStore";

/**
 * Right-side pane listing precomputed scenarios (trajectories) from the active
 * HDF5 store. Selecting one loads its trajectory into the results view without
 * rebuilding the network (all scenarios share one topology). Renders nothing
 * when no store is available, so ordinary configs are unaffected.
 */
export function ScenarioPane() {
  const { available, scenarios, activeId, loading, error, refresh, setActive } =
    useScenarioStore();

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!available || scenarios.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm text-foreground">Scenarios</h3>
        <span className="text-xs text-muted-foreground">{scenarios.length}</span>
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      <ul className="space-y-1 max-h-[70vh] overflow-y-auto pr-1">
        {scenarios.map((s) => {
          const isActive = s.id === activeId;
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => void setActive(s.id)}
                disabled={loading}
                title={
                  s.final_temperature_K != null
                    ? `T_final ≈ ${Math.round(s.final_temperature_K)} K` +
                      (s.solid_carbon_yield_pct != null
                        ? ` · C(s) ${s.solid_carbon_yield_pct.toFixed(1)}%`
                        : "")
                    : undefined
                }
                className={[
                  "w-full text-left rounded-md px-2 py-1.5 text-xs transition-colors",
                  "border",
                  isActive
                    ? "border-blue-500 bg-blue-500/10 text-foreground"
                    : "border-transparent hover:bg-muted text-foreground",
                ].join(" ")}
              >
                <div className="font-medium">{s.label}</div>
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
  );
}
