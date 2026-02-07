import { useSelectionStore } from "@/stores/selectionStore";
import type { SimulationResults } from "@/types/simulation";

interface Props {
  results: SimulationResults;
}

export function ThermoReportTab({ results }: Props) {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const reports = results.reactor_reports as Record<
    string,
    Record<string, unknown>
  > | undefined;

  if (!reports || Object.keys(reports).length === 0) {
    return <p className="text-sm text-muted-foreground">No thermo reports.</p>;
  }

  if (selectedElement?.type !== "node") {
    return (
      <p className="text-sm text-muted-foreground">
        Select a node to view thermo details.
      </p>
    );
  }

  const selectedId = String(selectedElement.data.id);
  const report = reports[selectedId];

  if (!report) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a node to view thermo details.
      </p>
    );
  }

  return (
    <div className="space-y-4 max-h-96 overflow-y-auto">
      <div className="rounded border border-border p-3">
        <h4 className="text-sm font-medium text-foreground mb-2">{selectedId}</h4>
        {report.reactor_report && typeof report.reactor_report === "string" ? (
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap mb-2">
            {report.reactor_report}
          </pre>
        ) : null}
        {report.thermo_report && typeof report.thermo_report === "string" ? (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              Full thermo report
            </summary>
            <pre className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">
              {report.thermo_report}
            </pre>
          </details>
        ) : null}
      </div>
    </div>
  );
}
