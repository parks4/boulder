import { useState, useCallback, useEffect, useMemo } from "react";
import { useThemeStore } from "@/stores/themeStore";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useAddEntityModalStore } from "@/stores/addEntityModalStore";
import { useSimulationSSE } from "@/hooks/useSimulationSSE";
import { useScenarioFocus } from "@/hooks/useScenarioFocus";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { startSimulation } from "@/api/simulations";
import { fetchDefaultConfig, fetchPreloadedConfig } from "@/api/configs";
import { fetchCachedResult } from "@/api/resultCache";
import { NetworkCard } from "@/components/panels/NetworkCard";
import { SimulateCard } from "@/components/panels/SimulateCard";
import { PropertiesPanel } from "@/components/panels/PropertiesPanel";
import { ScenarioPane } from "@/components/panels/ScenarioPane";
import { YamlPane } from "@/components/panels/YamlPane";
import { PaneToggle, PaneResizer } from "@/components/layout/paneControls";
import { useLayoutStore } from "@/stores/layoutStore";
import { useScenarioStore } from "@/stores/scenarioStore";
import { ReactorGraph } from "@/components/graph/ReactorGraph";
import { ResultsTabs } from "@/components/results/ResultsTabs";
import { SimulationOverlay } from "@/components/simulation/SimulationOverlay";
import { AddReactorModal } from "@/components/modals/AddReactorModal";
import { AddMFCModal } from "@/components/modals/AddMFCModal";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

export function AppShell() {
  const { theme, toggleTheme } = useThemeStore();
  const { config, setConfig } = useConfigStore();
  const { isRunning, beginSimulationRun, startSimulation: setStarted, setError, setResults } =
    useSimulationStore();
  const { reactorModal, connectionModal, closeAddReactor, closeAddConnection } =
    useAddEntityModalStore();
  const {
    leftCollapsed,
    rightCollapsed,
    leftWidth,
    rightWidth,
    toggleLeft,
    yamlPaneOpen,
    yamlWidth,
    openYamlPane,
  } = useLayoutStore();
  const scenariosAvailable = useScenarioStore((s) => s.available);
  const refreshScenarios = useScenarioStore((s) => s.refresh);

  // Discover available scenarios once so the right pane can appear.
  useEffect(() => {
    void refreshScenarios();
  }, [refreshScenarios]);

  // Connect SSE stream
  useSimulationSSE();

  // Follow scenario-focus pushes (external dashboard → load scenario live).
  useScenarioFocus();

  // Ctrl/Cmd+B toggles the left sidebar (Claude-desktop convention).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleLeft();
        requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleLeft]);

  // Load preloaded config if available, otherwise load default config on mount.
  // After a successful preloaded-config fetch, check for a matching cache entry
  // so outputs are visible immediately without re-running (issue #51).
  useEffect(() => {
    fetchPreloadedConfig()
      .then((resp) => {
        if (resp.preloaded && resp.config) {
          setConfig(resp.config, resp.filename || "config.yaml", resp.yaml);
          toast.success(`Loaded ${resp.filename || "configuration"}`);

          // Try to populate the UI with cached results for this config.
          return fetchCachedResult().then((cacheResp) => {
            if (!cacheResp.cached) return;

            const result = cacheResp.result;
            setResults(result);

            // Sync graph topology: apply updated_nodes / updated_connections
            // exactly as the SSE complete handler does.
            if (result.updated_nodes != null && result.updated_connections != null) {
              const currentConfig = useConfigStore.getState().config;
              const frontendMeta = new Map<string, Record<string, unknown>>();
              for (const n of currentConfig.nodes) {
                const off = (n.metadata as Record<string, unknown> | null)?.layout_offset;
                if (off !== undefined) frontendMeta.set(n.id, { layout_offset: off });
              }
              setConfig({
                ...currentConfig,
                nodes: result.updated_nodes.map((n) => {
                  const extra = frontendMeta.get(n.id);
                  return {
                    id: n.id,
                    type: n.type,
                    group: n.group ?? null,
                    properties: n.properties ?? {},
                    metadata: extra
                      ? { ...(n.metadata ?? {}), ...extra }
                      : (n.metadata ?? null),
                    network_class: n.network_class ?? null,
                  };
                }),
                connections: result.updated_connections.map((c) => ({
                  id: c.id,
                  source: c.source,
                  target: c.target,
                  type: c.type,
                  properties: c.properties ?? {},
                  metadata: c.metadata ?? null,
                  group: c.group ?? null,
                  logical: c.logical ?? null,
                  mechanism_switch: c.mechanism_switch ?? null,
                })),
              });
            }

            const created = cacheResp.meta.created_at;
            const ageMin = Math.round((Date.now() / 1000 - created) / 60);
            const ageStr = ageMin < 2 ? "just now" : `${ageMin} min ago`;
            toast.success(`Loaded cached results from ${ageStr}. Re-run skipped.`);
          });
        } else {
          // No preloaded config, load default
          return fetchDefaultConfig().then((defResp) => {
            if (defResp) setConfig(defResp.config, "default.yaml", defResp.yaml);
          });
        }
      })
      .catch(() => {
        /* API not available yet */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keyboard shortcut: Ctrl+Enter
  const handleRunSimulation = useCallback(async () => {
    if (isRunning || config.nodes.length === 0) return;
    beginSimulationRun();
    try {
      const resp = await startSimulation(config);
      setStarted(resp.simulation_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed: ${msg}`);
      setError(msg);
    }
  }, [isRunning, config, beginSimulationRun, setStarted, setError]);

  useKeyboardShortcuts(handleRunSimulation);

  // Host branding published by a Boulder plugin (e.g. {name: "MyApp", version: "1.2"}).
  const [branding, setBranding] = useState<{ name?: string; version?: string } | null>(
    null,
  );
  useEffect(() => {
    fetch("/api/ui/branding")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setBranding(data?.branding ?? null))
      .catch(() => setBranding(null));
  }, []);

  // Title priority: per-config metadata > plugin branding > "Boulder".
  const headerTitle = useMemo(() => {
    const raw = config.metadata?.gui_app_title;
    if (typeof raw === "string") {
      const t = raw.trim();
      if (t) return t;
    }
    if (branding?.name?.trim()) return branding.name.trim();
    return "Boulder";
  }, [config.metadata, branding]);

  // Version shown next to the title (metadata.gui_app_version > plugin branding).
  const headerVersion = useMemo(() => {
    const raw = config.metadata?.gui_app_version;
    if (typeof raw === "string" && raw.trim()) return raw.trim();
    return branding?.version?.trim() || null;
  }, [config.metadata, branding]);

  useEffect(() => {
    document.title = headerTitle;
  }, [headerTitle]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <PaneToggle side="left" />
          <h1 className="text-xl font-bold">{headerTitle}</h1>
          {headerVersion && (
            <span
              className="text-xs text-muted-foreground"
              title={`version ${headerVersion}`}
            >
              v{headerVersion}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {scenariosAvailable && <PaneToggle side="right" />}
          <Button
            onClick={toggleTheme}
            variant="secondary"
            size="sm"
            title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
          >
          {theme === "light" ? (
            <span className="flex items-center gap-1.5">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
              </svg>
              Dark
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2" />
                <path d="M12 20v2" />
                <path d="m4.93 4.93 1.41 1.41" />
                <path d="m17.66 17.66 1.41 1.41" />
                <path d="M2 12h2" />
                <path d="M20 12h2" />
                <path d="m6.34 17.66-1.41 1.41" />
                <path d="m19.07 4.93-1.41 1.41" />
              </svg>
              Light
            </span>
          )}
          </Button>
        </div>
      </header>

      {/* Main layout: collapsible + draggable left/right sidebars around a flex center. */}
      <div className="flex w-full max-w-[1600px] mx-auto p-4 items-start">
        {/* Left sidebar (Network / Simulate / Properties) */}
        {!leftCollapsed && (
          <>
            <aside
              style={{ width: leftWidth }}
              className="shrink-0 space-y-4 overflow-y-auto max-h-[calc(100vh-5rem)] pr-1"
            >
              <NetworkCard onEditYaml={openYamlPane} />
              <SimulateCard />
              <PropertiesPanel />
            </aside>
            <PaneResizer side="left" />
          </>
        )}

        {/* Center panel (graph + results) */}
        <main className="flex-1 min-w-0 space-y-4 px-1">
          <ReactorGraph />
          <ResultsTabs />
        </main>

        {/* Right scenario-inspector pane (hidden when no store / collapsed) */}
        {scenariosAvailable && !rightCollapsed && (
          <>
            <PaneResizer side="right" />
            <aside
              style={{ width: rightWidth }}
              className="shrink-0 space-y-4 overflow-y-auto max-h-[calc(100vh-5rem)] pl-1"
            >
              <ScenarioPane />
            </aside>
          </>
        )}

        {/* YAML editor pane — opened on demand from Network's "Edit YAML",
            docked right of the Scenario pane so it can sit alongside the
            graph instead of blocking it. */}
        {yamlPaneOpen && (
          <>
            <PaneResizer side="yaml" />
            <aside style={{ width: yamlWidth }} className="shrink-0 pl-1">
              <YamlPane />
            </aside>
          </>
        )}
      </div>

      {/* Overlays and modals */}
      <SimulationOverlay />
      <AddReactorModal
        // Remount (fresh form state) whenever it's opened with a different
        // stage, instead of syncing defaultGroup into state via an effect.
        key={reactorModal.open ? `open-${reactorModal.group ?? ""}` : "closed"}
        open={reactorModal.open}
        onClose={closeAddReactor}
        defaultGroup={reactorModal.group}
      />
      <AddMFCModal
        key={
          connectionModal.open
            ? `open-${connectionModal.group ?? ""}-${connectionModal.source ?? ""}`
            : "closed"
        }
        open={connectionModal.open}
        onClose={closeAddConnection}
        defaultGroup={connectionModal.group}
        defaultSource={connectionModal.source}
      />
    </div>
  );
}
