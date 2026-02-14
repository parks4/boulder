import type { SimulationResults } from "@/types/simulation";

interface Props {
  results: SimulationResults;
}

export function SummaryTab({ results }: Props) {
  const formatNumber = (n: number) => {
    if (!Number.isFinite(n)) return String(n);
    const fixed = n.toFixed(3);
    return fixed.replace(/\.?0+$/, "");
  };

  const formatSummaryLine = (row: Record<string, unknown>) => {
    const label = typeof row.label === "string" ? row.label : undefined;
    const reactor = typeof row.reactor === "string" ? row.reactor : undefined;
    const quantity = typeof row.quantity === "string" ? row.quantity : undefined;
    const unit = typeof row.unit === "string" ? row.unit : "";
    const error = typeof row.error === "string" ? row.error : undefined;
    const value = row.value;

    const displayLabel = label ?? [reactor, quantity].filter(Boolean).join(" ") ?? "Output";

    if (error) return `${displayLabel}: ERROR - ${error}`;
    if (typeof value === "number") return `${displayLabel}: ${formatNumber(value)}${unit ? ` ${unit}` : ""}`;
    if (value == null) return `${displayLabel}: (no value)`;

    return `${displayLabel}: ${String(value)}${unit ? ` ${unit}` : ""}`;
  };

  return (
    <div className="space-y-4">
      {results.elapsed_time != null && (
        <p className="text-sm text-foreground">
          Elapsed time: <span className="font-mono">{results.elapsed_time.toFixed(2)}s</span>
        </p>
      )}

      {Array.isArray(results.summary) && results.summary.length > 0 && (
        <div className="space-y-1">
          {results.summary.map((row, i) => (
            <div key={i} className="text-sm text-foreground">
              {formatSummaryLine(row as Record<string, unknown>)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
