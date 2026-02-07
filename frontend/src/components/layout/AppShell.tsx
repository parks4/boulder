import { useState, useCallback, useEffect } from "react";
import { useThemeStore } from "@/stores/themeStore";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSimulationSSE } from "@/hooks/useSimulationSSE";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { startSimulation } from "@/api/simulations";
import { fetchDefaultConfig, fetchPreloadedConfig } from "@/api/configs";
import { EditNetworkCard } from "@/components/panels/EditNetworkCard";
import { SimulateCard } from "@/components/panels/SimulateCard";
import { PropertiesPanel } from "@/components/panels/PropertiesPanel";
import { ReactorGraph } from "@/components/graph/ReactorGraph";
import { ResultsTabs } from "@/components/results/ResultsTabs";
import { SimulationOverlay } from "@/components/simulation/SimulationOverlay";
import { YAMLEditorModal } from "@/components/modals/YAMLEditorModal";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

export function AppShell() {
  const { theme, toggleTheme } = useThemeStore();
  const { config, fileName, setConfig } = useConfigStore();
  const { isRunning, startSimulation: setStarted } = useSimulationStore();
  const [showYamlEditor, setShowYamlEditor] = useState(false);

  // Connect SSE stream
  useSimulationSSE();

  // Load preloaded config if available, otherwise load default config on mount
  useEffect(() => {
    fetchPreloadedConfig()
      .then((resp) => {
        if (resp.preloaded && resp.config) {
          setConfig(resp.config, resp.filename || "config.yaml", resp.yaml);
          toast.success(`Loaded ${resp.filename || "configuration"}`);
        } else {
          // No preloaded config, load default
          return fetchDefaultConfig();
        }
      })
      .then((resp) => {
        // Only runs if fetchDefaultConfig was called
        if (resp) {
          setConfig(resp.config, "default.yaml", resp.yaml);
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
    try {
      const resp = await startSimulation(config);
      setStarted(resp.simulation_id);
      toast.success("Simulation started");
    } catch (err) {
      toast.error(`Failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [isRunning, config, setStarted]);

  useKeyboardShortcuts(handleRunSimulation);

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">Boulder</h1>
          {fileName && (
            <Button
              id="config-file-name-span"
              onClick={() => setShowYamlEditor(true)}
              variant="link"
              size="sm"
              className="px-0 h-auto"
            >
              {fileName}
            </Button>
          )}
        </div>
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
      </header>

      {/* Main layout: 3-col left + 9-col right (12-col grid) */}
      <div className="grid grid-cols-12 gap-4 p-4 max-w-[1600px] mx-auto">
        {/* Left panel (3 cols) */}
        <aside className="col-span-12 md:col-span-3 space-y-4">
          <EditNetworkCard />
          <SimulateCard />
          <PropertiesPanel />
        </aside>

        {/* Right panel (9 cols) */}
        <main className="col-span-12 md:col-span-9 space-y-4">
          <ReactorGraph />
          <ResultsTabs />
        </main>
      </div>

      {/* Overlays and modals */}
      <SimulationOverlay />
      <YAMLEditorModal
        open={showYamlEditor}
        onClose={() => setShowYamlEditor(false)}
      />
    </div>
  );
}
