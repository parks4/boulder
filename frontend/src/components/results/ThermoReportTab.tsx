import type { SimulationResults } from "@/types/simulation";

interface Props {
  results: SimulationResults;
}

export function ThermoReportTab({ results }: Props) {
  const reports = results.reactor_reports as Record<
    string,
    Record<string, unknown>
  > | undefined;

  if (!reports || Object.keys(reports).length === 0) {
    return <p className="text-sm text-muted-foreground">No thermo reports.</p>;
  }

  return (
    <div className="space-y-4 max-h-96 overflow-y-auto">
      {Object.entries(reports).map(([rid, report]) => (
        <div key={rid} className="rounded border border-border p-3">
          <h4 className="text-sm font-medium text-foreground mb-2">{rid}</h4>
          {report.reactor_report && (
            <pre className="text-xs text-muted-foreground whitespace-pre-wrap mb-2">
              {String(report.reactor_report)}
            </pre>
          )}
          {report.thermo_report && (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                Full thermo report
              </summary>
              <pre className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">
                {String(report.thermo_report)}
              </pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}
