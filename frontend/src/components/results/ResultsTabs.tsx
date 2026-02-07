import { useState, lazy, Suspense } from "react";
import { cn } from "@/lib/cn";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSelectionStore } from "@/stores/selectionStore";
import { PlotsTab } from "./PlotsTab";
import { SummaryTab } from "./SummaryTab";
import { ErrorTab } from "./ErrorTab";

const SankeyTab = lazy(() => import("./SankeyTab").then((m) => ({ default: m.SankeyTab })));
const ThermoReportTab = lazy(() =>
  import("./ThermoReportTab").then((m) => ({ default: m.ThermoReportTab })),
);

const TABS = ["Plots", "Sankey", "Thermo", "Summary", "Error"] as const;
type Tab = (typeof TABS)[number];

export function ResultsTabs() {
  const results = useSimulationStore((s) => s.results);
  const progress = useSimulationStore((s) => s.progress);
  const error = useSimulationStore((s) => s.error);
  const [activeTab, setActiveTab] = useState<Tab>("Plots");

  const data = results ?? progress;
  if (!data && !error) return null;

  return (
    <div id="simulation-results-card" className="rounded-lg border border-border bg-card">
      <div className="flex border-b border-border">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors",
              activeTab === tab
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="p-4">
        {activeTab === "Plots" && data && <PlotsTab data={data} />}
        {activeTab === "Sankey" && results && (
          <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
            <SankeyTab results={results} />
          </Suspense>
        )}
        {activeTab === "Thermo" && results && (
          <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
            <ThermoReportTab results={results} />
          </Suspense>
        )}
        {activeTab === "Summary" && results && <SummaryTab results={results} />}
        {activeTab === "Error" && <ErrorTab error={error} />}
      </div>
    </div>
  );
}
