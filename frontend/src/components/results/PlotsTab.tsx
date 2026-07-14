import { useCallback, useMemo, useState } from "react";
import Plot from "react-plotly.js";
import { coerceNumericSeries, pressureYAxis } from "@/lib/plotAxis";
import { useConfigStore } from "@/stores/configStore";
import { useSelectionStore } from "@/stores/selectionStore";
import { useThemeStore } from "@/stores/themeStore";
import type { SimulationProgress } from "@/types/simulation";

interface NodePlotConfig {
  hideSpecies: Set<string>;
  showSpecies: string[];
}

function traceVisibility(
  species: string,
  hideSpecies: Set<string>,
): true | "legendonly" {
  return hideSpecies.has(species) ? "legendonly" : true;
}

interface Props {
  data: SimulationProgress;
}

function traceModeForSamples(sampleCount: number): "lines" | "lines+markers" {
  return sampleCount > 1 ? "lines" : "lines+markers";
}

export function PlotsTab({ data }: Props) {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const theme = useThemeStore((s) => s.theme);
  const configNodes = useConfigStore((s) => s.config.nodes);

  // Shared x-range: zoom/pan on any plot synchronizes all of them
  // (double-click autoscale resets the whole set).
  const [xRange, setXRange] = useState<[number, number] | null>(null);
  const syncXRelayout = useCallback((event: unknown) => {
    const e = event as Record<string, unknown>;
    if (e["xaxis.autorange"]) {
      setXRange(null);
    } else if (
      e["xaxis.range[0]"] !== undefined &&
      e["xaxis.range[1]"] !== undefined
    ) {
      setXRange([Number(e["xaxis.range[0]"]), Number(e["xaxis.range[1]"])]);
    } else if (Array.isArray(e["xaxis.range"])) {
      const r = e["xaxis.range"] as [unknown, unknown];
      setXRange([Number(r[0]), Number(r[1])]);
    }
  }, []);
  const xRangeProps = xRange
    ? { range: [xRange[0], xRange[1]], autorange: false as const }
    : {};

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

  // Per-node `plot_options: {hide_species, show_species}` (STONE node
  // property) lets an example author hide dominant/uninteresting species
  // (e.g. N2, O2) and force minor-but-relevant ones (e.g. reaction
  // intermediates that never crack the top-12-by-magnitude heuristic below)
  // into the chart by default -- the user can still click a hidden trace's
  // legend entry to reveal it.
  const plotConfig: NodePlotConfig = useMemo(() => {
    const node = selectedReactorId
      ? configNodes.find((n) => n.id === selectedReactorId)
      : undefined;
    const raw = (node?.properties?.plot_options ?? {}) as {
      hide_species?: string[];
      show_species?: string[];
    };
    return {
      hideSpecies: new Set(raw.hide_species ?? []),
      showSpecies: raw.show_species ?? [],
    };
  }, [configNodes, selectedReactorId]);

  const MAIN_SPECIES_MIN_FRACTION = 1e-4;
  const MAIN_SPECIES_MAX_COUNT = 12;

  const mainSpeciesMole = useMemo(() => {
    const X = reactorSeries?.X ?? {};
    const ranked = Object.entries(X)
      .map(([name, arr]) => ({
        name,
        max: Math.max(...(arr ?? []), 0),
      }))
      .filter((s) => s.max >= MAIN_SPECIES_MIN_FRACTION)
      .sort((a, b) => b.max - a.max)
      .slice(0, MAIN_SPECIES_MAX_COUNT)
      .map((s) => s.name);
    const forced = plotConfig.showSpecies.filter(
      (name) => name in X && !ranked.includes(name),
    );
    return [...ranked, ...forced];
  }, [reactorSeries?.X, plotConfig.showSpecies]);

  const mainSpeciesMass = useMemo(() => {
    const Y = reactorSeries?.Y ?? {};
    const ranked = Object.entries(Y)
      .map(([name, arr]) => ({
        name,
        max: Math.max(...(arr ?? []), 0),
      }))
      .filter((s) => s.max >= MAIN_SPECIES_MIN_FRACTION)
      .sort((a, b) => b.max - a.max)
      .slice(0, MAIN_SPECIES_MAX_COUNT)
      .map((s) => s.name);
    const forced = plotConfig.showSpecies.filter(
      (name) => name in Y && !ranked.includes(name),
    );
    return [...ranked, ...forced];
  }, [reactorSeries?.Y, plotConfig.showSpecies]);

  if (!data.times.length && !reactorSeries?.is_spatial && !reactorSeries?.is_residence) {
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

  // --- Axial (PFR) or residence-time (closed CSTR / torch) profiles ---
  if (reactorSeries?.is_spatial || reactorSeries?.is_residence) {
    const isResidence = Boolean(reactorSeries?.is_residence);
    const xAxis = isResidence
      ? (reactorSeries.t ?? [])
      : (reactorSeries.x ?? []);
    const xLabel = isResidence ? "Residence time (s)" : "Position (m)";
    const coordLabel = isResidence ? "Residence time" : "Position";
    const profileTraceMode = traceModeForSamples(xAxis.length);

    const moleFractionTraces = mainSpeciesMole.map((species) => ({
      x: xAxis,
      y: reactorSeries.X?.[species] ?? [],
      type: "scatter" as const,
      mode: profileTraceMode,
      name: species,
      line: { width: 2 },
      visible: traceVisibility(species, plotConfig.hideSpecies),
    }));

    const massFractionTraces = mainSpeciesMass.map((species) => ({
      x: xAxis,
      y: reactorSeries.Y?.[species] ?? [],
      type: "scatter" as const,
      mode: profileTraceMode,
      name: species,
      line: { width: 2 },
      visible: traceVisibility(species, plotConfig.hideSpecies),
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
                mode: profileTraceMode,
                name: selectedReactorId,
                line: { width: 2 },
              },
            ]}
            layout={{
              ...layoutDefaults,
              title: { text: `Temperature vs ${coordLabel}`, font: { size: 14 } },
              xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor, ...xRangeProps },
              yaxis: { title: { text: "Temperature (°C)", font: { size: 12 } }, gridcolor },
            }}
            config={{ responsive: true, displayModeBar: false }}
            onRelayout={syncXRelayout}
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
                y: coerceNumericSeries(reactorSeries.P),
                type: "scatter",
                mode: profileTraceMode,
                name: selectedReactorId,
                line: { width: 2 },
              },
            ]}
            layout={{
              ...layoutDefaults,
              title: { text: `Pressure vs ${coordLabel}`, font: { size: 14 } },
              xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor, ...xRangeProps },
              yaxis: pressureYAxis(gridcolor),
            }}
            config={{ responsive: true, displayModeBar: false }}
            onRelayout={syncXRelayout}
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
                  text: `Mole fraction vs ${coordLabel} (main species)`,
                  font: { size: 14 },
                },
                xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor, ...xRangeProps },
                yaxis: {
                  title: { text: "Mole fraction", font: { size: 12 } },
                  gridcolor,
                  tickformat: ".2e",
                },
              }}
              config={{ responsive: true, displayModeBar: false }}
              onRelayout={syncXRelayout}
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
                  text: `Mass fraction vs ${coordLabel} (main species)`,
                  font: { size: 14 },
                },
                xaxis: { title: { text: xLabel, font: { size: 12 } }, gridcolor, ...xRangeProps },
                yaxis: {
                  title: { text: "Mass fraction", font: { size: 12 } },
                  gridcolor,
                  tickformat: ".2e",
                },
              }}
              config={{ responsive: true, displayModeBar: false }}
              onRelayout={syncXRelayout}
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
            onRelayout={syncXRelayout}
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
            onRelayout={syncXRelayout}
            useResizeHandler
            className="w-full"
          />
        </div>
      </div>
    );
  }

  // --- Default: standard time-series plots ---
  const times = data.times;
  const timeTraceMode = traceModeForSamples(times.length);

  const moleFractionTraces = mainSpeciesMole.map((species) => ({
    x: times,
    y: reactorSeries?.X?.[species] ?? [],
    type: "scatter" as const,
    mode: timeTraceMode,
    name: species,
    line: { width: 2 },
    visible: traceVisibility(species, plotConfig.hideSpecies),
  }));

  const massFractionTraces = mainSpeciesMass.map((species) => ({
    x: times,
    y: reactorSeries?.Y?.[species] ?? [],
    type: "scatter" as const,
    mode: timeTraceMode,
    name: species,
    line: { width: 2 },
    visible: traceVisibility(species, plotConfig.hideSpecies),
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
              mode: timeTraceMode,
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
              ...xRangeProps,
            },
            yaxis: {
              title: { text: "Temperature (°C)", font: { size: 12 } },
              gridcolor,
            },
          }}
          config={{ responsive: true, displayModeBar: false }}
          onRelayout={syncXRelayout}
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
              y: coerceNumericSeries(data.reactors_series[selectedReactorId]?.P),
              type: "scatter" as const,
              mode: timeTraceMode,
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
              ...xRangeProps,
            },
            yaxis: pressureYAxis(gridcolor),
          }}
          config={{ responsive: true, displayModeBar: false }}
          onRelayout={syncXRelayout}
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
                ...xRangeProps,
              },
              yaxis: {
                title: { text: "Mole fraction", font: { size: 12 } },
                gridcolor,
                tickformat: ".2e",
              },
            }}
            config={{ responsive: true, displayModeBar: false }}
            onRelayout={syncXRelayout}
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
                ...xRangeProps,
              },
              yaxis: {
                title: { text: "Mass fraction", font: { size: 12 } },
                gridcolor,
                tickformat: ".2e",
              },
            }}
            config={{ responsive: true, displayModeBar: false }}
            onRelayout={syncXRelayout}
            useResizeHandler
            className="w-full"
          />
        </div>
      )}
    </div>
  );
}
