import { useState, useCallback, useEffect } from "react";
import { useThemeStore } from "@/stores/themeStore";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSimulationSSE } from "@/hooks/useSimulationSSE";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { startSimulation } from "@/api/simulations";
import { fetchDefaultConfig } from "@/api/configs";
import { EditNetworkCard } from "@/components/panels/EditNetworkCard";
import { SimulateCard } from "@/components/panels/SimulateCard";
import { PropertiesPanel } from "@/components/panels/PropertiesPanel";
import { ReactorGraph } from "@/components/graph/ReactorGraph";
import { ResultsTabs } from "@/components/results/ResultsTabs";
import { SimulationOverlay } from "@/components/simulation/SimulationOverlay";
import { YAMLEditorModal } from "@/components/modals/YAMLEditorModal";
import { toast } from "sonner";

export function AppShell() {
  const { theme, toggleTheme } = useThemeStore();
  const { config, fileName, setConfig } = useConfigStore();
  const { isRunning, startSimulation: setStarted } = useSimulationStore();
  const [showYamlEditor, setShowYamlEditor] = useState(false);

  // Connect SSE stream
  useSimulationSSE();

  // Load default config on mount
  useEffect(() => {
    fetchDefaultConfig()
      .then((resp) => setConfig(resp.config, "default.yaml", resp.yaml))
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
            <button
              id="config-file-name-span"
              onClick={() => setShowYamlEditor(true)}
              className="text-sm text-muted-foreground hover:text-foreground underline"
            >
              {fileName}
            </button>
          )}
        </div>
        <button
          onClick={toggleTheme}
          className="px-3 py-1.5 text-sm rounded-md bg-secondary text-secondary-foreground hover:opacity-80"
        >
          {theme === "light" ? "Dark" : "Light"}
        </button>
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
