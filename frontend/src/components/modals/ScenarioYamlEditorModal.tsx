import { useState, useEffect, lazy, Suspense } from "react";
import { fetchScenarioSource, updateScenario } from "@/api/scenarios";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

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
 * Scoped scenario editor — like YAMLEditorModal but limited to one scenario's
 * overlay subtree (``scenario.<id>``) instead of the whole config file.
 * Editing here never touches the base network, so there's nothing to sync
 * against a live structured config: the overlay text is the whole story.
 */
export function ScenarioYamlEditorModal({
  scenarioId,
  baseScenarioId,
  onClose,
  onSaved,
}: Props) {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

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
      id="scenario-yaml-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-3xl h-[80vh] bg-card border border-border rounded-lg shadow-lg flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div>
            <h2 className="text-lg font-semibold text-foreground">
              Scenario: {scenarioId}
            </h2>
            {baseScenarioId && (
              <p className="text-xs text-muted-foreground">
                Base: {baseScenarioId}
              </p>
            )}
          </div>
          <Button
            onClick={onClose}
            variant="ghost"
            size="icon"
            className="text-lg"
            aria-label="Close"
          >
            ×
          </Button>
        </div>

        <div className="flex-1 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
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
                  className="w-full h-full p-4 font-mono text-sm bg-background text-foreground resize-none"
                />
              }
            >
              <MonacoEditor
                height="100%"
                language="yaml"
                value={value}
                onChange={(v) => setValue(v ?? "")}
                theme="vs-dark"
                options={{
                  minimap: { enabled: false },
                  wordWrap: "on",
                  fontSize: 13,
                }}
              />
            </Suspense>
          )}
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-border">
          <Button onClick={onClose} variant="secondary" size="sm">
            Cancel
          </Button>
          <Button
            id="save-scenario-yaml-btn"
            onClick={() => void handleSave()}
            disabled={saving || loading || !!loadError}
            variant="primary"
            size="sm"
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
