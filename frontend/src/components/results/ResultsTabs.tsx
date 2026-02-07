import { useEffect, useState, lazy, Suspense } from "react";
import { useSimulationStore } from "@/stores/simulationStore";
import { Button } from "@/components/ui/Button";
import { PlotsTab } from "./PlotsTab";
import { SummaryTab } from "./SummaryTab";
import { ErrorTab } from "./ErrorTab";

const SankeyTab = lazy(() => import("./SankeyTab").then((m) => ({ default: m.SankeyTab })));
const ThermoReportTab = lazy(() =>
  import("./ThermoReportTab").then((m) => ({ default: m.ThermoReportTab })),
);

const BASE_TABS = ["Plots", "Sankey", "Thermo", "Summary"] as const;
const ERROR_TAB_LABEL = "⚠️Error" as const;
type Tab = (typeof BASE_TABS)[number] | typeof ERROR_TAB_LABEL;

export function ResultsTabs() {
  const results = useSimulationStore((s) => s.results);
  const progress = useSimulationStore((s) => s.progress);
  const error = useSimulationStore((s) => s.error);
  const [activeTab, setActiveTab] = useState<Tab>("Plots");

  // If the error clears while viewing the Error tab, move back to a safe tab.
  // Important: must be declared before any conditional returns to keep hook order stable.
  useEffect(() => {
    if (!error && activeTab === ERROR_TAB_LABEL) setActiveTab("Plots");
  }, [error, activeTab]);

  const data = results ?? progress;
  if (!data && !error) return null;

  const tabs: Tab[] = error ? [...BASE_TABS, ERROR_TAB_LABEL] : [...BASE_TABS];

  return (
    <div id="simulation-results-card" className="rounded-lg border border-border bg-card">
      <div className="flex border-b border-border">
        {tabs.map((tab) => (
          <Button
            key={tab}
            onClick={() => setActiveTab(tab)}
            variant="tab"
            size="tab"
            data-active={activeTab === tab}
          >
            {tab}
          </Button>
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
        {activeTab === ERROR_TAB_LABEL && <ErrorTab error={error} />}
      </div>
    </div>
  );
}
