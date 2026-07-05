import { useEffect, useState, useRef, lazy, Suspense } from "react";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSelectionStore } from "@/stores/selectionStore";
import { useConfigStore } from "@/stores/configStore";
import { useThemeStore } from "@/stores/themeStore";
import { useResultsTabStore } from "@/stores/resultsTabStore";
import { fetchPlugins, renderPlugin } from "@/api/plugins";
import { Button } from "@/components/ui/Button";
import { PlotsTab } from "./PlotsTab";
import { ConvergenceTab } from "./ConvergenceTab";
import { SummaryTab } from "./SummaryTab";
import { ErrorTab } from "./ErrorTab";
import { PluginTab } from "./PluginTab";
import type { PluginMeta, PluginRenderData } from "@/types/plugin";

const SankeyTab = lazy(() => import("./SankeyTab").then((m) => ({ default: m.SankeyTab })));
const ThermoReportTab = lazy(() =>
  import("./ThermoReportTab").then((m) => ({ default: m.ThermoReportTab })),
);

const BASE_TABS = ["Plots", "Sankey", "Thermo", "Summary", "Convergence"] as const;
const ERROR_TAB_LABEL = "⚠️Error" as const;
type Tab = (typeof BASE_TABS)[number] | typeof ERROR_TAB_LABEL | string;

export function ResultsTabs() {
  const results = useSimulationStore((s) => s.results);
  const progress = useSimulationStore((s) => s.progress);
  const error = useSimulationStore((s) => s.error);
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const config = useConfigStore((s) => s.config);
  const theme = useThemeStore((s) => s.theme);
  const activeTab = useResultsTabStore((s) => s.activeTab);
  const setActiveTab = useResultsTabStore((s) => s.setActiveTab);
  /** Resolved tab for UI: explicit choice, else Sankey when results exist, else Plots. */
  const displayTab = activeTab ?? (results ? "Sankey" : "Plots");
  const [plugins, setPlugins] = useState<PluginMeta[]>([]);
  const [pluginData, setPluginData] = useState<Record<string, PluginRenderData>>({});
  const [pluginLoading, setPluginLoading] = useState<Record<string, boolean>>({});

  // Track in-flight requests and what was already fetched (cache key per plugin)
  const loadingRef = useRef<Record<string, boolean>>({});
  const fetchedKeyRef = useRef<Record<string, string>>({});

  // Version counter bumped whenever the results OBJECT changes (new run,
  // scenario selected, cache restore) so plugin tabs re-render their content —
  // a plain `!!results` presence check would keep stale plugin output.
  const resultsVersionRef = useRef(0);
  const lastResultsRef = useRef<unknown>(null);
  if (results !== lastResultsRef.current) {
    lastResultsRef.current = results;
    resultsVersionRef.current += 1;
  }

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

  // Selection-scoped plugins only surface while a matching element is
  // selected: any selection for plain requires_selection plugins, a node of a
  // listed reactor kind when supported_node_types is set.
  const visiblePlugins = plugins.filter((p) => {
    if (!p.requires_selection) return true;
    if (!selectedElement) return false;
    if (p.supported_node_types && p.supported_node_types.length > 0) {
      return (
        selectedElement.type === "node" &&
        p.supported_node_types.includes(String(selectedElement.data.type))
      );
    }
    return true;
  });

  // Load plugin content when a plugin tab is active.
  // Uses a cache key per plugin so we only re-fetch when something the
  // plugin actually cares about has changed.
  const activePlugin = visiblePlugins.find((p) => p.label === activeTab);
  useEffect(() => {
    if (!activePlugin) return;

    const pluginId = activePlugin.id;

    // Build a cache key from the inputs this plugin depends on. The selection
    // is always part of the key: even selection-optional plugins may narrow
    // their content to the selected element (only the active tab fetches, so
    // the extra render calls are negligible).
    const cacheKey = JSON.stringify({
      results: resultsVersionRef.current,  // bumps on every new results object
      theme,
      sel: selectedElement,
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

  const pluginTabs = visiblePlugins.map((p) => p.label);
  const tabs: Tab[] = [
    ...BASE_TABS,
    ...pluginTabs,
    ...(error ? [ERROR_TAB_LABEL] : []),
  ];
  // If the active tab just disappeared (its plugin's selection was cleared),
  // fall back to a safe base tab instead of rendering an empty pane.
  const safeTab: Tab = tabs.includes(displayTab)
    ? displayTab
    : results
      ? "Sankey"
      : "Plots";

  return (
    <div id="simulation-results-card" className="rounded-lg border border-border bg-card">
      <div className="flex border-b border-border overflow-x-auto">
        {tabs.map((tab) => (
          <Button
            key={tab}
            onClick={() => setActiveTab(tab)}
            variant="tab"
            size="tab"
            data-active={safeTab === tab}
          >
            {tab}
          </Button>
        ))}
      </div>

      <div className="p-4">
        {safeTab === "Plots" && data && <PlotsTab data={data} />}
        {safeTab === "Convergence" && data && <ConvergenceTab data={data} />}
        {safeTab === "Sankey" && results && (
          <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
            <SankeyTab results={results} />
          </Suspense>
        )}
        {safeTab === "Thermo" && results && (
          <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
            <ThermoReportTab results={results} />
          </Suspense>
        )}
        {safeTab === "Summary" && results && <SummaryTab results={results} />}
        {safeTab === ERROR_TAB_LABEL && <ErrorTab error={error} />}

        {/* Dynamic plugin tabs */}
        {visiblePlugins.map((plugin) => {
          if (safeTab !== plugin.label) return null;
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
