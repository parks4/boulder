import { memo, useEffect, useState } from "react";
import Plot from "react-plotly.js";
import { mapSankeyNodeColors } from "@/lib/cytoscapeNodeColor";
import { hasSankeyData } from "@/lib/sankeyData";
import { useThemeStore } from "@/stores/themeStore";
import type { SimulationResults } from "@/types/simulation";

interface Props {
  results: SimulationResults;
}

/**
 * Theme-only link colors (mass / enthalpy / heat). Species bands are resolved
 * to hex on the server via ``sankey_links_for_api`` (plugin palette when registered).
 */
const LIGHT_LINK_COLORS: Record<string, string> = {
  mass: "pink",
  enthalpy: "purple",
  heat: "#D3D3D3",
};

const DARK_LINK_COLORS: Record<string, string> = {
  mass: "#B0B0B0",
  enthalpy: "#4A90E2",
  heat: "#D3D3D3",
};

function isLiteralCssColor(s: string): boolean {
  return s.startsWith("#") || s.startsWith("rgb");
}

function mapSankeyLinkColors(
  semantic: unknown[] | undefined,
  theme: "light" | "dark",
): string[] | undefined {
  if (!semantic?.length) return undefined;
  const table = theme === "dark" ? DARK_LINK_COLORS : LIGHT_LINK_COLORS;
  return semantic.map((c) => {
    if (typeof c !== "string") return "grey";
    if (isLiteralCssColor(c)) return c;
    return table[c] ?? "grey";
  });
}

// plotly.js hardcodes a 500ms grow-in transition for sankey node/link traces
// (src/traces/sankey/constants.js), applied unconditionally in its d3
// render code — there is no data/layout/config option that reaches it
// (`transition` config, `staticPlot`, etc. don't touch it). Rendering the
// plot hidden for slightly longer than that lets the animation play out
// off-screen instead of flashing on every new scenario/result.
const SANKEY_POP_IN_MS = 550;

/**
 * Memoized: ResultsTabs re-renders every ~1s while a sweep is polling
 * (scenarioProgress/lastLine churn) even when this scenario's own results
 * haven't changed. Plotly rebuilds its whole SVG on every render — a plain
 * component would redraw (visibly flicker) on every one of those unrelated
 * ticks. Skipping re-render when `results` itself hasn't changed keeps it
 * static except when there's actually new data to show.
 */
export const SankeyTab = memo(function SankeyTab({ results }: Props) {
  const theme = useThemeStore((s) => s.theme);

  // Hidden (not unmounted, so Plotly still sizes and lays it out normally)
  // until plotly's built-in pop-in transition would have finished.
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    setSettled(false);
    const t = setTimeout(() => setSettled(true), SANKEY_POP_IN_MS);
    return () => clearTimeout(t);
  }, [results]);

  if (!hasSankeyData(results)) {
    return <p className="text-sm text-muted-foreground">No Sankey data available.</p>;
  }

  const links = results.sankey_links as Record<string, unknown[]>;

  const source = links["source"] ?? [];
  const target = links["target"] ?? [];
  const value = links["value"] ?? [];
  const n = source.length;

  const rawLabel = links["label"];
  const linkLabels =
    Array.isArray(rawLabel) && rawLabel.length === n ? rawLabel : undefined;

  const rawColor = links["color"];
  const linkColors =
    Array.isArray(rawColor) && rawColor.length === n
      ? mapSankeyLinkColors(rawColor, theme)
      : undefined;

  const linkTrace: Record<string, unknown> = {
    source,
    target,
    value,
  };
  if (linkLabels) linkTrace.label = linkLabels;
  if (linkColors) linkTrace.color = linkColors;

  const nodeColors = mapSankeyNodeColors(
    results.sankey_nodes,
    results.reactor_reports as Record<string, unknown> | undefined,
    results.updated_nodes,
    theme,
  );

  return (
    <div style={{ visibility: settled ? "visible" : "hidden" }}>
      <Plot
        data={[
          {
            type: "sankey" as const,
            node: {
              label: results.sankey_nodes,
              color: nodeColors,
              pad: 15,
              thickness: 20,
            },
            link: linkTrace,
          } as Plotly.Data,
        ]}
        layout={{
          paper_bgcolor: "transparent",
          font: { color: theme === "dark" ? "#ccc" : "#333" },
          margin: { t: 20, b: 20, l: 20, r: 20 },
          height: 400,
        }}
        config={{ responsive: true, displayModeBar: false }}
        useResizeHandler
        className="w-full"
      />
    </div>
  );
});
