import { useState, useEffect, lazy, Suspense } from "react";
import { FileCode, X } from "lucide-react";
import { fetchScenarioSource, updateScenario } from "@/api/scenarios";
import { useThemeStore } from "@/stores/themeStore";
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
 * instead of the whole config file. Editing here never touches the base
 * network, so there's nothing to sync against a live structured config: the
 * overlay text is the whole story.
 */
export function ScenarioYamlPane({ scenarioId, baseScenarioId, onClose, onSaved }: Props) {
  const theme = useThemeStore((s) => s.theme);
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const isSimulating = useSimulationStore((s) => s.isRunning);
  const isSweeping = useSweepRunStore((s) => s.sweeping);
  const isCalculating = isSimulating || isSweeping;

  useEffect(() => {
    if (!scenarioId) return;
    setLoadError(null);
    setLoading(true);
    fetchScenarioSource(scenarioId)
      .then((resp) => setValue(resp.yaml))
      .catch((err) => {
        setLoadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }, [scenarioId]);

  if (!scenarioId) return null;

  const handleSave = async () => {
    if (isCalculating) {
      toast.error("Wait for the current calculation to finish before saving YAML changes.");
      return;
    }
    setSaving(true);
    try {
      await updateScenario(scenarioId, value);
      toast.success(`Scenario "${scenarioId}" saved`);
      onSaved?.(scenarioId);
      onClose();
    } catch (err) {
      toast.error(
        `Could not save scenario: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSaving(false);
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
