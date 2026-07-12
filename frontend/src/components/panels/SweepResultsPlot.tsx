import { useMemo } from "react";
import Plot from "react-plotly.js";
import { useThemeStore } from "@/stores/themeStore";
import type { ScenarioMeta } from "@/api/scenarios";

interface Props {
  scenarios: ScenarioMeta[];
}

const KPI_PREFIX = "final_X_";

/**
 * Sweep-results chart: swept KPIs (e.g. final mole fractions) vs. the swept
 * parameter (t0_K), across every scenario in the active store — the
 * parameter-sweep equivalent of upstream Cantera examples' "species vs.
 * temperature" plots (e.g. continuous_reactor.py). Lives in the Scenario
 * (sweep) pane, not the main Plots tab: a sweep produces one point per run,
 * not a single reactor's time/space trajectory.
 *
 * Renders nothing when the store has no scenarios or no KPI attrs (e.g. a
 * plain multi-case store with no sweep runner attaching final_X_* attrs).
 */
export function SweepResultsPlot({ scenarios }: Props) {
  const theme = useThemeStore((s) => s.theme);

  const { xValues, series } = useMemo(() => {
    const withX = scenarios.filter((s) => typeof s.t0_K === "number");
    const sorted = [...withX].sort((a, b) => (a.t0_K ?? 0) - (b.t0_K ?? 0));
    const kpiKeys = new Set<string>();
    for (const s of sorted) {
      for (const key of Object.keys(s)) {
        if (key.startsWith(KPI_PREFIX) && typeof s[key] === "number") {
          kpiKeys.add(key);
        }
      }
    }
    const x = sorted.map((s) => s.t0_K as number);
    const traces = Array.from(kpiKeys)
      .sort()
      .map((key) => ({
        name: key.slice(KPI_PREFIX.length),
        y: sorted.map((s) => (s[key] as number | undefined) ?? null),
      }));
    return { xValues: x, series: traces };
  }, [scenarios]);

  if (xValues.length === 0 || series.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <h3 className="font-semibold text-sm text-foreground">Sweep results</h3>
      <Plot
        data={series.map((s) => ({
          x: xValues,
          y: s.y,
          type: "scatter" as const,
          mode: "lines+markers" as const,
          name: s.name,
        }))}
        layout={{
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { color: theme === "dark" ? "#ccc" : "#333", size: 11 },
          margin: { t: 10, b: 40, l: 50, r: 10 },
          height: 220,
          showlegend: true,
          legend: { x: 1, xanchor: "right" as const, y: 1 },
          xaxis: {
            title: { text: "Swept temperature (K)" },
            gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
          },
          yaxis: {
            title: { text: "Mole fraction" },
            gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
          },
        }}
        config={{ displaylogo: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}
