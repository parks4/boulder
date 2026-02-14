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

  // Track in-flight requests and what was already fetched (cache key per plugin)
  const loadingRef = useRef<Record<string, boolean>>({});
  const fetchedKeyRef = useRef<Record<string, string>>({});

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

  // Load plugin content when a plugin tab is active.
  // Uses a cache key per plugin so we only re-fetch when something the
  // plugin actually cares about has changed.
  const activePlugin = plugins.find((p) => p.label === activeTab);
  useEffect(() => {
    if (!activePlugin) return;

    const pluginId = activePlugin.id;

    // Build a cache key from the inputs this plugin depends on.
    // Selection-independent plugins ignore selectedElement entirely.
    const cacheKey = JSON.stringify({
      results: !!results,  // only care about presence, not reference
      theme,
      ...(activePlugin.requires_selection
        ? { sel: selectedElement }
        : {}),
    });

    // Already fetched with the same context — nothing to do.
    if (fetchedKeyRef.current[pluginId] === cacheKey) return;
    // Already in-flight — skip duplicate request.
    if (loadingRef.current[pluginId]) return;

    loadingRef.current[pluginId] = true;
    fetchedKeyRef.current[pluginId] = cacheKey;
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
        // Clear cache key so a retry is possible
        fetchedKeyRef.current[pluginId] = "";
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
  }); // no dependency array — runs every render, but the cache-key
      // guard above ensures we only actually fetch when needed.

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
