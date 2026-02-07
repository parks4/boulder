import type { PluginRenderData } from "@/types/plugin";

interface Props {
  data: PluginRenderData;
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

  const content = data.data;

  switch (content.type) {
    case "image":
      return (
        <img
          src={String(content.src)}
          alt={String(content.alt ?? "Plugin output")}
          className="max-w-full rounded"
        />
      );
    case "table": {
      const headers = (content.headers as string[]) ?? [];
      const rows = (content.rows as unknown[][]) ?? [];
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
          dangerouslySetInnerHTML={{ __html: String(content.content) }}
        />
      );
    case "text":
    default:
      return (
        <pre className="text-xs text-foreground whitespace-pre-wrap">
          {String(content.content ?? JSON.stringify(content, null, 2))}
        </pre>
      );
  }
}
