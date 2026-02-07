import Plot from "react-plotly.js";
import { useThemeStore } from "@/stores/themeStore";
import type { SimulationResults } from "@/types/simulation";

interface Props {
  results: SimulationResults;
}

export function SankeyTab({ results }: Props) {
  const theme = useThemeStore((s) => s.theme);

  if (!results.sankey_links || !results.sankey_nodes) {
    return <p className="text-sm text-muted-foreground">No Sankey data available.</p>;
  }

  const links = results.sankey_links as Record<string, unknown[]>;

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
          link: {
            source: links["source"] ?? [],
            target: links["target"] ?? [],
            value: links["value"] ?? [],
          },
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
