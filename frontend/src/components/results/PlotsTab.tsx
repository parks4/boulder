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

  // reactorSeries must be resolved before any early return so that the
  // useMemo calls below are always executed (React forbids conditional hooks).
  const reactorSeries = selectedReactorId
    ? data.reactors_series[selectedReactorId]
    : undefined;

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

  if (!data.times.length && !reactorSeries?.is_spatial) {
    return <p className="text-sm text-muted-foreground">No data yet.</p>;
  }

  if (!selectedReactorId) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a reactor node to view plots.
      </p>
    );
  }

  const gridcolor = theme === "dark" ? "#333" : "#e0e0e0";

  // --- Spatial reactor: axial profiles ---
  if (reactorSeries?.is_spatial) {
    const xAxis = reactorSeries.x ?? [];
    const xLabel = "Position (m)";

    const moleFractionTraces = mainSpeciesMole.map((species) => ({
      x: xAxis,
      y: reactorSeries.X?.[species] ?? [],
      type: "scatter" as const,
      mode: "lines" as const,
      name: species,
      line: { width: 2 },
    }));

    const massFractionTraces = mainSpeciesMass.map((species) => ({
      x: xAxis,
      y: reactorSeries.Y?.[species] ?? [],
      type: "scatter" as const,
      mode: "lines" as const,
      name: species,
      line: { width: 2 },
    }));

    return (
      <div className="space-y-4">
        {/* Temperature vs Position */}
        <div>
          <Plot
            data={[
              {
                x: xAxis,
                y: reactorSeries.T?.map((t) => t - 273.15) ?? [],
                type: "scatter",
                mode: "lines",
                name: selectedReactorId,
                line: { width: 2 },
              },
            ]}
            layout={{
              ...layoutDefaults,
              title: { text: "Temperature vs Position", font: { size: 14 } },
              xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor },
              yaxis: { title: { text: "Temperature (°C)", font: { size: 12 } }, gridcolor },
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        </div>

        {/* Pressure vs Position */}
        <div>
          <Plot
            data={[
              {
                x: xAxis,
                y: reactorSeries.P ?? [],
                type: "scatter",
                mode: "lines",
                name: selectedReactorId,
                line: { width: 2 },
              },
            ]}
            layout={{
              ...layoutDefaults,
              title: { text: "Pressure vs Position", font: { size: 14 } },
              xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor },
              yaxis: { title: { text: "Pressure (Pa)", font: { size: 12 } }, gridcolor },
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        </div>

        {/* Mole fractions vs Position */}
        {moleFractionTraces.length > 0 && (
          <div>
            <Plot
              data={moleFractionTraces}
              layout={{
                ...layoutDefaults,
                title: {
                  text: "Mole fraction vs Position (main species)",
                  font: { size: 14 },
                },
                xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor },
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
          </div>
        )}

        {/* Mass fractions vs Position */}
        {massFractionTraces.length > 0 && (
          <div>
            <Plot
              data={massFractionTraces}
              layout={{
                ...layoutDefaults,
                title: {
                  text: "Mass fraction vs Position (main species)",
                  font: { size: 14 },
                },
                xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor },
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
          </div>
        )}
      </div>
    );
  }

  // --- PSR: steady-state composition pie charts ---
  if (reactorSeries?.is_psr) {
    // Last point in each array is the converged steady-state
    const lastMole = Object.fromEntries(
      Object.entries(reactorSeries.X ?? {}).map(([sp, arr]) => [
        sp,
        (arr as number[]).at(-1) ?? 0,
      ]),
    );
    const lastMass = Object.fromEntries(
      Object.entries(reactorSeries.Y ?? {}).map(([sp, arr]) => [
        sp,
        (arr as number[]).at(-1) ?? 0,
      ]),
    );

    const moleLabels = mainSpeciesMole;
    const moleValues = moleLabels.map((sp) => lastMole[sp] ?? 0);
    const massLabels = mainSpeciesMass;
    const massValues = massLabels.map((sp) => lastMass[sp] ?? 0);

    const pieMoleOther =
      1 - moleValues.reduce((a, b) => a + b, 0);
    const pieMassOther =
      1 - massValues.reduce((a, b) => a + b, 0);

    const moleLabelsAll = pieMoleOther > 1e-6
      ? [...moleLabels, "Other"]
      : moleLabels;
    const moleValuesAll = pieMoleOther > 1e-6
      ? [...moleValues, pieMoleOther]
      : moleValues;

    const massLabelsAll = pieMassOther > 1e-6
      ? [...massLabels, "Other"]
      : massLabels;
    const massValuesAll = pieMassOther > 1e-6
      ? [...massValues, pieMassOther]
      : massValues;

    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Steady-state composition — time-resolved convergence is in the{" "}
          <strong>Convergence</strong> tab.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Mole fraction pie */}
          <Plot
            data={[
              {
                labels: moleLabelsAll,
                values: moleValuesAll,
                type: "pie",
                textinfo: "label+percent",
                hoverinfo: "label+value+percent",
              },
            ]}
            layout={{
              ...layoutDefaults,
              height: 350,
              title: { text: "Mole fractions (steady state)", font: { size: 14 } },
              showlegend: false,
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />

          {/* Mass fraction pie */}
          <Plot
            data={[
              {
                labels: massLabelsAll,
                values: massValuesAll,
                type: "pie",
                textinfo: "label+percent",
                hoverinfo: "label+value+percent",
              },
            ]}
            layout={{
              ...layoutDefaults,
              height: 350,
              title: { text: "Mass fractions (steady state)", font: { size: 14 } },
              showlegend: false,
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            className="w-full"
          />
        </div>
      </div>
    );
  }

  // --- Default: standard time-series plots ---
  const times = data.times;

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
              gridcolor,
            },
            yaxis: {
              title: { text: "Temperature (°C)", font: { size: 12 } },
              gridcolor,
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
              gridcolor,
            },
            yaxis: {
              title: { text: "Pressure (Pa)", font: { size: 12 } },
              gridcolor,
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
                gridcolor,
              },
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
                gridcolor,
              },
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
        </div>
      )}
    </div>
  );
}
