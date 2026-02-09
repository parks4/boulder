import { useEffect, useState, useRef, lazy, Suspense } from "react";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSelectionStore } from "@/stores/selectionStore";
import { useConfigStore } from "@/stores/configStore";
import { useThemeStore } from "@/stores/themeStore";
import { fetchPlugins, renderPlugin } from "@/api/plugins";
import { Button } from "@/components/ui/Button";
import { PlotsTab } from "./PlotsTab";
import { SummaryTab } from "./SummaryTab";
import { ErrorTab } from "./ErrorTab";
import { PluginTab } from "./PluginTab";
import type { PluginMeta, PluginRenderData } from "@/types/plugin";

const SankeyTab = lazy(() => import("./SankeyTab").then((m) => ({ default: m.SankeyTab })));
const ThermoReportTab = lazy(() =>
  import("./ThermoReportTab").then((m) => ({ default: m.ThermoReportTab })),
);

const BASE_TABS = ["Plots", "Sankey", "Thermo", "Summary"] as const;
const ERROR_TAB_LABEL = "⚠️Error" as const;
type Tab = (typeof BASE_TABS)[number] | typeof ERROR_TAB_LABEL | string;

export function ResultsTabs() {
  const results = useSimulationStore((s) => s.results);
  const progress = useSimulationStore((s) => s.progress);
  const error = useSimulationStore((s) => s.error);
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const config = useConfigStore((s) => s.config);
  const theme = useThemeStore((s) => s.theme);

  const [activeTab, setActiveTab] = useState<Tab>("Plots");
  const [plugins, setPlugins] = useState<PluginMeta[]>([]);
  const [pluginData, setPluginData] = useState<Record<string, PluginRenderData>>({});
  const [pluginLoading, setPluginLoading] = useState<Record<string, boolean>>({});

  // Use a ref to track in-flight requests without causing re-renders
  const loadingRef = useRef<Record<string, boolean>>({});

  // Fetch available plugins when simulation results arrive
  useEffect(() => {
    if (!results && !progress) return;
    fetchPlugins()
      .then(setPlugins)
      .catch(() => setPlugins([]));
  }, [results, progress]);

  // If the error clears while viewing the Error tab, move back to a safe tab.
  useEffect(() => {
    if (!error && activeTab === ERROR_TAB_LABEL) setActiveTab("Plots");
  }, [error, activeTab]);

  // Auto-load plugin data when the active tab changes to a plugin tab,
  // or when the selection / context changes while on a plugin tab.
  useEffect(() => {
    const plugin = plugins.find((p) => p.label === activeTab);
    if (!plugin) return;

    const pluginId = plugin.id;

    // Skip if already loading this plugin
    if (loadingRef.current[pluginId]) return;
    loadingRef.current[pluginId] = true;
    setPluginLoading((prev) => ({ ...prev, [pluginId]: true }));

    renderPlugin(pluginId, {
      simulation_data: results as Record<string, unknown> | null,
      selected_element: selectedElement as Record<string, unknown> | null,
      config: config as unknown as Record<string, unknown> | null,
      theme,
    })
      .then((data) => {
        setPluginData((prev) => ({ ...prev, [pluginId]: data }));
      })
      .catch((err) => {
        setPluginData((prev) => ({
          ...prev,
          [pluginId]: {
            available: false,
            message: `Failed to render plugin: ${err}`,
          },
        }));
      })
      .finally(() => {
        loadingRef.current[pluginId] = false;
        setPluginLoading((prev) => ({ ...prev, [pluginId]: false }));
      });
  }, [activeTab, plugins, selectedElement, results, config, theme]);

  const data = results ?? progress;
  if (!data && !error) return null;

  const pluginTabs = plugins.map((p) => p.label);
  const tabs: Tab[] = [
    ...BASE_TABS,
    ...pluginTabs,
    ...(error ? [ERROR_TAB_LABEL] : []),
  ];

  return (
    <div id="simulation-results-card" className="rounded-lg border border-border bg-card">
      <div className="flex border-b border-border overflow-x-auto">
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

        {/* Dynamic plugin tabs */}
        {plugins.map((plugin) => {
          if (activeTab !== plugin.label) return null;
          const pData = pluginData[plugin.id];
          const loading = pluginLoading[plugin.id];
          if (loading) {
            return (
              <p key={plugin.id} className="text-sm text-muted-foreground">
                Loading plugin...
              </p>
            );
          }
          if (!pData) return null;
          return <PluginTab key={plugin.id} data={pData} />;
        })}
      </div>
    </div>
  );
}
