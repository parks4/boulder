import Plot from "react-plotly.js";
import { useThemeStore } from "@/stores/themeStore";
import type { SimulationResults } from "@/types/simulation";

interface Props {
  results: SimulationResults;
}

/**
 * Theme-only link colors (mass / enthalpy / heat). Species bands are resolved
 * to hex on the server via ``sankey_links_for_api`` (Bloc ``plot.py`` when installed).
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

export function SankeyTab({ results }: Props) {
  const theme = useThemeStore((s) => s.theme);

  if (!results.sankey_links || !results.sankey_nodes) {
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

  return (
    <Plot
      data={[
        {
          type: "sankey" as const,
          node: {
            label: results.sankey_nodes,
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
  );
}
