import { useMemo } from "react";
import Plot from "react-plotly.js";
import { useSelectionStore } from "@/stores/selectionStore";
import { useThemeStore } from "@/stores/themeStore";
import type { SimulationProgress } from "@/types/simulation";

interface Props {
  data: SimulationProgress;
}

export function ConvergenceTab({ data }: Props) {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const theme = useThemeStore((s) => s.theme);

  const selectedReactorId = useMemo(() => {
    if (selectedElement?.type !== "node") return null;
    const selectedId = String(selectedElement.data.id);
    return data.reactors_series[selectedId] ? selectedId : null;
  }, [selectedElement, data.reactors_series]);

  const layoutDefaults = useMemo(
    () => ({
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: theme === "dark" ? "#ccc" : "#333", size: 12 },
      margin: { t: 40, b: 60, l: 70, r: 30 },
      height: 300,
      showlegend: true,
      legend: { x: 1, xanchor: "right" as const, y: 1 },
    }),
    [theme],
  );

  const MAIN_SPECIES_MIN_FRACTION = 1e-4;
  const MAIN_SPECIES_MAX_COUNT = 12;

  const series = selectedReactorId
    ? data.reactors_series[selectedReactorId]
    : undefined;

  const mainSpeciesMole = useMemo(() => {
    const X = series?.X ?? {};
    return Object.entries(X)
      .map(([name, arr]) => ({ name, max: Math.max(...(arr ?? []), 0) }))
      .filter((s) => s.max >= MAIN_SPECIES_MIN_FRACTION)
      .sort((a, b) => b.max - a.max)
      .slice(0, MAIN_SPECIES_MAX_COUNT)
      .map((s) => s.name);
  }, [series?.X]);

  const mainSpeciesMass = useMemo(() => {
    const Y = series?.Y ?? {};
    return Object.entries(Y)
      .map(([name, arr]) => ({ name, max: Math.max(...(arr ?? []), 0) }))
      .filter((s) => s.max >= MAIN_SPECIES_MIN_FRACTION)
      .sort((a, b) => b.max - a.max)
      .slice(0, MAIN_SPECIES_MAX_COUNT)
      .map((s) => s.name);
  }, [series?.Y]);

  if (!data.times.length && !series?.is_spatial) {
    return <p className="text-sm text-muted-foreground">No data yet.</p>;
  }

  if (!selectedReactorId) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a reactor node to view convergence data.
      </p>
    );
  }

  const gridcolor = theme === "dark" ? "#333" : "#e0e0e0";

  // --- Spatial reactor: FBS convergence plot ---
  if (series?.is_spatial) {
    const fbsHistory = series.fbs_convergence ?? [];
    const iters = fbsHistory.map((_, i) => i);

    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Forward-Backward Sweep convergence — heat loss at each iteration.
        </p>
        {fbsHistory.length > 0 ? (
          <Plot
            data={[
              {
                x: iters,
                y: fbsHistory,
                type: "scatter",
                mode: "lines+markers",
                name: "Φ (kW)",
                line: { width: 2 },
                marker: { size: 6 },
              },
            ]}
            layout={{
              ...layoutDefaults,
              title: { text: "FBS Heat-Loss Convergence", font: { size: 14 } },
              xaxis: {
                title: { text: "FBS Iteration", font: { size: 12 } },
                gridcolor,
                dtick: 1,
              },
              yaxis: {
                title: { text: "Heat loss Φ (kW)", font: { size: 12 } },
                gridcolor,
              },
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            No FBS convergence data available (adiabatic reactor?).
          </p>
        )}
      </div>
    );
  }

  // --- PSR: transient T / P / X / Y vs time ---
  if (series?.is_psr) {
    const times = data.times;

    const moleFractionTraces = mainSpeciesMole.map((sp) => ({
      x: times,
      y: series.X?.[sp] ?? [],
      type: "scatter" as const,
      mode: "lines" as const,
      name: sp,
      line: { width: 2 },
    }));

    const massFractionTraces = mainSpeciesMass.map((sp) => ({
      x: times,
      y: series.Y?.[sp] ?? [],
      type: "scatter" as const,
      mode: "lines" as const,
      name: sp,
      line: { width: 2 },
    }));

    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Transient approach to steady state (PSR time integration).
        </p>

        {/* Temperature vs time */}
        <Plot
          data={[
            {
              x: times,
              y: series.T?.map((t) => t - 273.15) ?? [],
              type: "scatter",
              mode: "lines",
              name: selectedReactorId,
              line: { width: 2 },
            },
          ]}
          layout={{
            ...layoutDefaults,
            title: { text: "Temperature vs Time", font: { size: 14 } },
            xaxis: { title: { text: "Time (s)", font: { size: 12 } }, gridcolor },
            yaxis: { title: { text: "Temperature (°C)", font: { size: 12 } }, gridcolor },
          }}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          className="w-full"
        />

        {/* Pressure vs time */}
        <Plot
          data={[
            {
              x: times,
              y: series.P ?? [],
              type: "scatter",
              mode: "lines",
              name: selectedReactorId,
              line: { width: 2 },
            },
          ]}
          layout={{
            ...layoutDefaults,
            title: { text: "Pressure vs Time", font: { size: 14 } },
            xaxis: { title: { text: "Time (s)", font: { size: 12 } }, gridcolor },
            yaxis: { title: { text: "Pressure (Pa)", font: { size: 12 } }, gridcolor },
          }}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          className="w-full"
        />

        {/* Mole fractions vs time */}
        {moleFractionTraces.length > 0 && (
          <Plot
            data={moleFractionTraces}
            layout={{
              ...layoutDefaults,
              title: { text: "Mole fraction vs Time (main species)", font: { size: 14 } },
              xaxis: { title: { text: "Time (s)", font: { size: 12 } }, gridcolor },
              yaxis: {
                title: { text: "Mole fraction", font: { size: 12 } },
                gridcolor,
                tickformat: ".2e",
              },
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        )}

        {/* Mass fractions vs time */}
        {massFractionTraces.length > 0 && (
          <Plot
            data={massFractionTraces}
            layout={{
              ...layoutDefaults,
              title: { text: "Mass fraction vs Time (main species)", font: { size: 14 } },
              xaxis: { title: { text: "Time (s)", font: { size: 12 } }, gridcolor },
              yaxis: {
                title: { text: "Mass fraction", font: { size: 12 } },
                gridcolor,
                tickformat: ".2e",
              },
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        )}
      </div>
    );
  }

  // --- All other reactor types ---
  return (
    <p className="text-sm text-muted-foreground">
      No convergence data available for this reactor type.
    </p>
  );
}
