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

  // Determine which reactors to plot (selected or all)
  const reactorIds = useMemo(() => {
    if (
      selectedElement?.type === "node" &&
      data.reactors_series[String(selectedElement.data.id)]
    ) {
      return [String(selectedElement.data.id)];
    }
    return Object.keys(data.reactors_series);
  }, [selectedElement, data.reactors_series]);

  const layoutDefaults = useMemo(
    () => ({
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: theme === "dark" ? "#ccc" : "#333" },
      margin: { t: 30, b: 40, l: 50, r: 10 },
      height: 250,
      xaxis: { title: "Time (s)" },
    }),
    [theme],
  );

  if (!data.times.length) {
    return <p className="text-sm text-muted-foreground">No data yet.</p>;
  }

  return (
    <div className="space-y-4">
      {/* Temperature plot */}
      <div id="temperature-plot-container">
        <Plot
          data={reactorIds.map((rid) => ({
            x: data.times,
            y: data.reactors_series[rid]?.T?.map((t: number) => t - 273.15) ?? [],
            type: "scatter" as const,
            mode: "lines" as const,
            name: `${rid} T`,
          }))}
          layout={{ ...layoutDefaults, yaxis: { title: "Temperature (°C)" } }}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          className="w-full"
        />
      </div>

      {/* Pressure plot */}
      <div>
        <Plot
          data={reactorIds.map((rid) => ({
            x: data.times,
            y: data.reactors_series[rid]?.P ?? [],
            type: "scatter" as const,
            mode: "lines" as const,
            name: `${rid} P`,
          }))}
          layout={{ ...layoutDefaults, yaxis: { title: "Pressure (Pa)" } }}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          className="w-full"
        />
      </div>
    </div>
  );
}
