import { useMemo } from "react";
import Plot from "react-plotly.js";
import { useSelectionStore } from "@/stores/selectionStore";
import { useThemeStore } from "@/stores/themeStore";
import type { SimulationProgress } from "@/types/simulation";

interface Props {
  data: SimulationProgress;
}

export function PlotsTab({ data }: Props) {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const theme = useThemeStore((s) => s.theme);

  // Determine which reactor to plot (selected only)
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

  if (!data.times.length) {
    return <p className="text-sm text-muted-foreground">No data yet.</p>;
  }

  if (!selectedReactorId) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a reactor node to view plots.
      </p>
    );
  }

  const reactorSeries = data.reactors_series[selectedReactorId];
  const times = data.times;

  // Main species for composition: max fraction > threshold, keep up to 12 species
  const MAIN_SPECIES_MIN_FRACTION = 1e-4;
  const MAIN_SPECIES_MAX_COUNT = 12;

  const mainSpeciesMole = useMemo(() => {
    const X = reactorSeries?.X ?? {};
    return Object.entries(X)
      .map(([name, arr]) => ({
        name,
        max: Math.max(...(arr ?? []), 0),
      }))
      .filter((s) => s.max >= MAIN_SPECIES_MIN_FRACTION)
      .sort((a, b) => b.max - a.max)
      .slice(0, MAIN_SPECIES_MAX_COUNT)
      .map((s) => s.name);
  }, [reactorSeries?.X]);

  const mainSpeciesMass = useMemo(() => {
    const Y = reactorSeries?.Y ?? {};
    return Object.entries(Y)
      .map(([name, arr]) => ({
        name,
        max: Math.max(...(arr ?? []), 0),
      }))
      .filter((s) => s.max >= MAIN_SPECIES_MIN_FRACTION)
      .sort((a, b) => b.max - a.max)
      .slice(0, MAIN_SPECIES_MAX_COUNT)
      .map((s) => s.name);
  }, [reactorSeries?.Y]);

  const moleFractionTraces = mainSpeciesMole.map((species) => ({
    x: times,
    y: reactorSeries?.X?.[species] ?? [],
    type: "scatter" as const,
    mode: "lines" as const,
    name: species,
    line: { width: 2 },
  }));

  const massFractionTraces = mainSpeciesMass.map((species) => ({
    x: times,
    y: reactorSeries?.Y?.[species] ?? [],
    type: "scatter" as const,
    mode: "lines" as const,
    name: species,
    line: { width: 2 },
  }));

  return (
    <div className="space-y-4">
      {/* Temperature plot */}
      <div id="temperature-plot-container">
        <Plot
          data={[
            {
              x: data.times,
              y:
                data.reactors_series[selectedReactorId]?.T?.map(
                  (t: number) => t - 273.15,
                ) ?? [],
              type: "scatter" as const,
              mode: "lines" as const,
              name: selectedReactorId,
              line: { width: 2 },
            },
          ]}
          layout={{
            ...layoutDefaults,
            title: { text: "Temperature vs Time", font: { size: 14 } },
            xaxis: {
              title: { text: "Time (s)", font: { size: 12 } },
              gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
            },
            yaxis: {
              title: { text: "Temperature (°C)", font: { size: 12 } },
              gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
            },
          }}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          className="w-full"
        />
      </div>

      {/* Pressure plot */}
      <div>
        <Plot
          data={[
            {
              x: data.times,
              y: data.reactors_series[selectedReactorId]?.P ?? [],
              type: "scatter" as const,
              mode: "lines" as const,
              name: selectedReactorId,
              line: { width: 2 },
            },
          ]}
          layout={{
            ...layoutDefaults,
            title: { text: "Pressure vs Time", font: { size: 14 } },
            xaxis: {
              title: { text: "Time (s)", font: { size: 12 } },
              gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
            },
            yaxis: {
              title: { text: "Pressure (Pa)", font: { size: 12 } },
              gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
            },
          }}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          className="w-full"
        />
      </div>

      {/* Mole fraction (composition) vs Time */}
      {moleFractionTraces.length > 0 && (
        <div>
          <Plot
            data={moleFractionTraces}
            layout={{
              ...layoutDefaults,
              title: {
                text: "Mole fraction vs Time (main species)",
                font: { size: 14 },
              },
              xaxis: {
                title: { text: "Time (s)", font: { size: 12 } },
                gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
              },
              yaxis: {
                title: { text: "Mole fraction", font: { size: 12 } },
                gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
                tickformat: ".2e",
              },
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        </div>
      )}

      {/* Mass fraction (composition) vs Time */}
      {massFractionTraces.length > 0 && reactorSeries?.Y && (
        <div>
          <Plot
            data={massFractionTraces}
            layout={{
              ...layoutDefaults,
              title: {
                text: "Mass fraction vs Time (main species)",
                font: { size: 14 },
              },
              xaxis: {
                title: { text: "Time (s)", font: { size: 12 } },
                gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
              },
              yaxis: {
                title: { text: "Mass fraction", font: { size: 12 } },
                gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
                tickformat: ".2e",
              },
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        </div>
      )}
    </div>
  );
}
