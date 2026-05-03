import { useState, useEffect, lazy, Suspense } from "react";
import { useConfigStore } from "@/stores/configStore";
import { parseYaml, syncConfig } from "@/api/configs";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));

interface Props {
  open: boolean;
  onClose: () => void;
}

export function YAMLEditorModal({ open, onClose }: Props) {
  const { config, originalYaml, setConfig } = useConfigStore();
  const [value, setValue] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncWarnings, setSyncWarnings] = useState<string[]>([]);

  // Sync YAML when modal opens: call /api/configs/sync to merge live config
  // into the original YAML (preserving comments and unit strings).
  useEffect(() => {
    if (!open) return;
    setSyncError(null);
    setSyncWarnings([]);

    if (!originalYaml) {
      setSyncError("No configuration available to edit.");
      return;
    }

    if (config.nodes.length === 0) {
      // Empty config — just show the raw original YAML.
      setValue(originalYaml);
      return;
    }

    setSyncing(true);
    syncConfig(config, originalYaml)
      .then((resp) => {
        setValue(resp.yaml);
        setSyncWarnings(resp.warnings ?? []);
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err);
        setSyncError(
          `Failed to sync YAML with current configuration: ${msg}. ` +
            "The displayed YAML may not match the live config — close and reopen, " +
            "or fix the configuration first.",
        );
        // Do NOT fall back to stale originalYaml — saving it would overwrite GUI edits.
      })
      .finally(() => setSyncing(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      const resp = await parseYaml(value);
      // Update both config and originalYaml so next open stays fresh.
      setConfig(resp.config, undefined, value);
      toast.success("YAML config updated");
      onClose();
    } catch (err) {
      toast.error(
        `Invalid YAML: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSaving(false);
    }
  };

  const canSave = !saving && !syncing && !syncError;

  return (
    <div
      id="config-yaml-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-3xl h-[80vh] bg-card border border-border rounded-lg shadow-lg flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">
            YAML Configuration Editor
          </h2>
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

        {syncWarnings.length > 0 && (
          <div
            id="sync-warnings-banner"
            className="px-4 py-2 text-xs bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-800 text-yellow-800 dark:text-yellow-300 space-y-0.5"
          >
            <p className="font-semibold">Sync warnings (non-blocking):</p>
            {syncWarnings.map((w, i) => (
              <p key={i}>{w}</p>
            ))}
          </div>
        )}

        <div className="flex-1 overflow-hidden">
          {syncing ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              Syncing YAML with current configuration…
            </div>
          ) : syncError ? (
            <div
              id="sync-error-message"
              className="flex items-center justify-center h-full text-destructive p-4 text-center text-sm"
            >
              {syncError}
            </div>
          ) : (
            <Suspense
              fallback={
                <textarea
                  id="config-yaml-editor"
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
            id="save-config-yaml-edit-btn"
            onClick={handleSave}
            disabled={!canSave}
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
