import { useSelectionStore } from "@/stores/selectionStore";
import { useConfigStore } from "@/stores/configStore";
import { kelvinToCelsius, formatNumber } from "@/lib/units";
import type { SimulationResults } from "@/types/simulation";

interface Props {
  results: SimulationResults;
}

export function ThermoReportTab({ results }: Props) {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const config = useConfigStore((s) => s.config);
  const reports = results.reactor_reports as Record<
    string,
    Record<string, unknown>
  > | undefined;

  // Mass Flow Controller selected: show mass flow, volumetric flows (from backend), gas composition, T, P (from source reactor)
  if (selectedElement?.type === "edge" && String(selectedElement.data.type) === "MassFlowController") {
    const mfcId = String(selectedElement.data.id);
    const sourceId = String(selectedElement.data.source);
    const targetId = String(selectedElement.data.target);
    const connection = config.connections.find((c) => c.id === mfcId);
    const props = (connection?.properties ?? {}) as Record<string, unknown>;
    const connectionReport = results.connection_reports?.[mfcId];
    const massFlowRate =
      typeof connectionReport?.mass_flow_rate === "number"
        ? connectionReport.mass_flow_rate
        : typeof props.mass_flow_rate === "number"
          ? props.mass_flow_rate
          : undefined;
    const volumetricFlowReal = typeof connectionReport?.volumetric_flow_real_m3_s === "number"
      ? connectionReport.volumetric_flow_real_m3_s
      : undefined;
    const volumetricFlowNormal = typeof connectionReport?.volumetric_flow_normal_m3_s === "number"
      ? connectionReport.volumetric_flow_normal_m3_s
      : undefined;
    const sourceReport = reports?.[sourceId];

    return (
      <div className="space-y-4 max-h-96 overflow-y-auto">
        <div className="rounded border border-border p-3">
          <h4 className="text-sm font-medium text-foreground mb-2">
            {mfcId} <span className="text-muted-foreground font-normal">(Mass Flow Controller)</span>
          </h4>
          <p className="text-xs text-muted-foreground mb-2">
            {sourceId} → {targetId}
          </p>
          <div className="space-y-2 text-xs">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Mass flow rate</span>
              <span className="font-mono text-foreground">
                {massFlowRate != null ? `${formatNumber(massFlowRate)} kg/s` : "—"}
              </span>
            </div>
            {volumetricFlowReal != null && (
              <div className="flex justify-between gap-2">
                <span className="text-muted-foreground">Volumetric flow (real)</span>
                <span className="font-mono text-foreground">{formatNumber(volumetricFlowReal, 6)} m³/s</span>
              </div>
            )}
            {volumetricFlowNormal != null && (
              <div className="flex justify-between gap-2">
                <span className="text-muted-foreground">Volumetric flow (normal, DIN 1343)</span>
                <span className="font-mono text-foreground">{formatNumber(volumetricFlowNormal, 6)} m³/s</span>
              </div>
            )}
            {sourceReport ? (
              <>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Temperature (source)</span>
                  <span className="font-mono text-foreground">
                    {typeof sourceReport.T === "number"
                      ? `${formatNumber(kelvinToCelsius(sourceReport.T), 2)} °C`
                      : "—"}
                  </span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Pressure (source)</span>
                  <span className="font-mono text-foreground">
                    {typeof sourceReport.P === "number"
                      ? `${formatNumber(Number(sourceReport.P), 2)} Pa`
                      : "—"}
                  </span>
                </div>
                {sourceReport.X && typeof sourceReport.X === "object" && !Array.isArray(sourceReport.X) ? (
                  <div className="pt-1">
                    <span className="text-muted-foreground block mb-1">Gas composition (mole fractions, source)</span>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-foreground">
                      {Object.entries(sourceReport.X as Record<string, number>)
                        .filter(([, v]) => Number(v) > 1e-10)
                        .sort((a, b) => b[1] - a[1])
                        .map(([species, x]) => (
                          <span key={species}>
                            {species}: {formatNumber(x, 4)}
                          </span>
                        ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-muted-foreground italic">Run simulation to see temperature, pressure and composition from source reactor.</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (!reports || Object.keys(reports).length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {selectedElement
          ? "No thermo reports. Run a simulation to see details."
          : "Select a node or Mass Flow Controller to view thermo details."}
      </p>
    );
  }

  if (selectedElement?.type !== "node") {
    return (
      <p className="text-sm text-muted-foreground">
        Select a node or Mass Flow Controller to view thermo details.
      </p>
    );
  }

  const selectedId = String(selectedElement.data.id);
  const report = reports[selectedId];

  if (!report) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a node or Mass Flow Controller to view thermo details.
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
