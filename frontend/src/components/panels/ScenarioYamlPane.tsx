import { useState, useEffect, useRef, lazy, Suspense } from "react";
import { FileCode, X } from "lucide-react";
import { fetchScenarioSource, renderFullYaml } from "@/api/scenarios";
import { useThemeStore } from "@/stores/themeStore";
import { useScenarioStore } from "@/stores/scenarioStore";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSweepRunStore } from "@/stores/sweepStore";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));

interface Props {
  scenarioId: string | null;
  /** The scenario this one was cloned from, if any — shown as "Base: <id>". */
  baseScenarioId?: string;
  onClose: () => void;
  /** Called after a successful save, so the caller can refresh the list. */
  onSaved?: (scenarioId: string) => void;
}

/**
 * Scoped scenario editor — same docked-pane chrome as `YamlPane` (so editing
 * BASELINE vs. a scenario feels like the same feature, not two different
 * UIs), but limited to one scenario's overlay subtree (`scenarios.<id>`)
 * instead of the whole config file. Nothing here touches disk — "Save"
 * updates this session's in-memory overlay (`scenarioStore.overlays`) only;
 * "Download full YAML" is the one way to get a complete, ready-to-run config
 * out of an edited scenario.
 */
export function ScenarioYamlPane({ scenarioId, baseScenarioId, onClose, onSaved }: Props) {
  const theme = useThemeStore((s) => s.theme);
  // Bumped by any scenario write, from any source (see scenarioStore's
  // applyOverlays and this pane's own onSaved wiring) -- used below to
  // refetch this pane's content when a *different* editor (e.g. the
  // Properties panel) changes the same scenario while this pane is open.
  const revision = useScenarioStore((s) => s.revision);
  const updateScenario = useScenarioStore((s) => s.updateScenario);
  const [value, setValue] = useState("");
  const [baseline, setBaseline] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const isSimulating = useSimulationStore((s) => s.isRunning);
  const isSweeping = useSweepRunStore((s) => s.sweeping);
  const isCalculating = isSimulating || isSweeping;

  const isDirty = value !== baseline;
  const isDirtyRef = useRef(isDirty);
  isDirtyRef.current = isDirty;

  useEffect(() => {
    if (!scenarioId) return;
    // Don't clobber an unsaved edit just because something *else* wrote to
    // this scenario (or any scenario) in the meantime -- same guard YamlPane
    // uses for the base config.
    if (isDirtyRef.current) return;
    setLoadError(null);
    setLoading(true);
    const overlay = useScenarioStore.getState().overlays[scenarioId] ?? {};
    fetchScenarioSource(scenarioId, overlay)
      .then((resp) => {
        setValue(resp.yaml);
        setBaseline(resp.yaml);
      })
      .catch((err) => {
        setLoadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- revision is an
    // intentional refetch trigger, not data this effect reads.
  }, [scenarioId, revision]);

  if (!scenarioId) return null;

  const handleSave = async () => {
    if (isCalculating) {
      toast.error("Wait for the current calculation to finish before saving YAML changes.");
      return;
    }
    setSaving(true);
    try {
      await updateScenario(scenarioId, value);
      toast.success(`Scenario "${scenarioId}" updated`);
      onSaved?.(scenarioId);
      onClose();
    } catch (err) {
      toast.error(
        `Could not update scenario: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDownloadFullYaml = async () => {
    setDownloading(true);
    try {
      const overlay = useScenarioStore.getState().overlays[scenarioId] ?? {};
      const resp = await renderFullYaml(scenarioId, overlay);
      const blob = new Blob([resp.yaml], { type: "text/yaml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${scenarioId}.yaml`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Downloaded ${scenarioId}.yaml`);
    } catch (err) {
      toast.error(
        `Could not render full YAML: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div
      id="scenario-yaml-pane"
      className="flex h-[calc(100vh-5rem)] flex-col rounded-lg border border-border bg-card"
    >
      <div className="flex items-center justify-between gap-2 border-b border-border p-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FileCode size={16} className="shrink-0 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground truncate">
            Scenario: {scenarioId}
          </h2>
          {baseScenarioId && (
            <span className="text-xs text-muted-foreground truncate">
              (base: {baseScenarioId})
            </span>
          )}
        </div>
        <Button onClick={onClose} variant="ghost" size="icon" aria-label="Close scenario YAML pane">
          <X size={16} />
        </Button>
      </div>

      {isCalculating && (
        <div
          id="scenario-yaml-locked-banner"
          className="px-3 py-2 text-xs bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-300 shrink-0"
        >
          A calculation is running — this scenario is locked until it finishes.
        </div>
      )}

      <div className="flex-1 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            Loading scenario…
          </div>
        ) : loadError ? (
          <div className="flex items-center justify-center h-full text-destructive p-4 text-center text-sm">
            {loadError}
          </div>
        ) : (
          <Suspense
            fallback={
              <textarea
                id="scenario-yaml-editor"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                readOnly={isCalculating}
                className="w-full h-full p-4 font-mono text-sm bg-background text-foreground resize-none"
              />
            }
          >
            <MonacoEditor
              height="100%"
              language="yaml"
              value={value}
              onChange={(v) => setValue(v ?? "")}
              theme={theme === "dark" ? "vs-dark" : "light"}
              options={{
                minimap: { enabled: false },
                wordWrap: "on",
                fontSize: 13,
                readOnly: isCalculating,
              }}
            />
          </Suspense>
        )}
      </div>

      <div className="flex justify-end gap-2 p-3 border-t border-border shrink-0">
        <Button
          id="download-full-scenario-yaml-btn"
          onClick={() => void handleDownloadFullYaml()}
          disabled={downloading || loading || !!loadError}
          variant="muted"
          size="sm"
          title="Download the full config (base + this scenario's overlay) as one YAML file"
        >
          {downloading ? "Rendering…" : "Download full YAML"}
        </Button>
        <Button onClick={onClose} variant="secondary" size="sm">
          Cancel
        </Button>
        <Button
          id="save-scenario-yaml-btn"
          onClick={() => void handleSave()}
          disabled={saving || loading || !!loadError || isCalculating}
          variant="primary"
          size="sm"
          title={isCalculating ? "Wait for the current calculation to finish" : undefined}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}
