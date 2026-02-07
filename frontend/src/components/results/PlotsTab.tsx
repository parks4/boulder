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
    </div>
  );
}
