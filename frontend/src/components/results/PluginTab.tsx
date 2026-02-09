import Plot from "react-plotly.js";
import { useThemeStore } from "@/stores/themeStore";
import type { PluginContentItem, PluginRenderData } from "@/types/plugin";

interface Props {
  data: PluginRenderData;
}

/**
 * Render a single content item (recursive for "grid" type).
 */
function RenderContent({ item }: { item: PluginContentItem }) {
  const theme = useThemeStore((s) => s.theme);

  switch (item.type) {
    case "image":
      return (
        <img
          src={String(item.src)}
          alt={String(item.alt ?? "Plugin output")}
          className="max-w-full rounded"
        />
      );

    case "table": {
      const headers = (item.headers as string[]) ?? [];
      const rows = (item.rows as unknown[][]) ?? [];
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {headers.map((h, i) => (
                  <th key={i} className="px-2 py-1 text-left text-xs font-medium text-muted-foreground">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b border-border">
                  {row.map((cell, j) => (
                    <td key={j} className="px-2 py-1 text-xs text-foreground">
                      {String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    case "html":
      return (
        <div
          className="prose prose-sm dark:prose-invert max-w-none"
          dangerouslySetInnerHTML={{ __html: String(item.content) }}
        />
      );

    case "plotly": {
      const figure = item.figure as { data?: unknown[]; layout?: Record<string, unknown> } | undefined;
      if (!figure) {
        return <p className="text-sm text-muted-foreground">No figure data</p>;
      }
      const layoutDefaults: Record<string, unknown> = {
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { color: theme === "dark" ? "#ccc" : "#333", size: 12 },
        margin: { t: 40, b: 60, l: 70, r: 30 },
        height: 350,
      };
      const mergedLayout = { ...layoutDefaults, ...(figure.layout ?? {}) };
      return (
        <Plot
          data={(figure.data ?? []) as Plotly.Data[]}
          layout={mergedLayout as Partial<Plotly.Layout>}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          className="w-full"
        />
      );
    }

    case "grid": {
      const columns = (item.columns as number) ?? 2;
      const items = (item.items as PluginContentItem[]) ?? [];
      return (
        <div
          className="gap-4"
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${columns}, 1fr)`,
          }}
        >
          {items.map((child, idx) => (
            <RenderContent key={idx} item={child} />
          ))}
        </div>
      );
    }

    case "error":
      return (
        <div className="rounded border border-destructive/50 bg-destructive/10 p-4">
          <h4 className="text-sm font-semibold text-destructive">{String(item.title ?? "Error")}</h4>
          <p className="mt-1 text-xs text-destructive/80">{String(item.message ?? "")}</p>
        </div>
      );

    case "text":
    default:
      return (
        <pre className="text-xs text-foreground whitespace-pre-wrap">
          {String(item.content ?? JSON.stringify(item, null, 2))}
        </pre>
      );
  }
}

/**
 * Generic renderer for plugin output data.
 * Renders based on the `type` field in the plugin response.
 */
export function PluginTab({ data }: Props) {
  if (!data.available) {
    return (
      <p className="text-sm text-muted-foreground">
        {data.message ?? "Plugin not available"}
      </p>
    );
  }

  if (!data.data) {
    return <p className="text-sm text-muted-foreground">No data</p>;
  }

  return <RenderContent item={data.data} />;
}
