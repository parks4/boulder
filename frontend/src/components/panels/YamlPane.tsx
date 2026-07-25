import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { FileCode, X } from "lucide-react";
import { useConfigStore } from "@/stores/configStore";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { useThemeStore } from "@/stores/themeStore";
import { parseYaml, syncConfig } from "@/api/configs";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));

/**
 * Full-height pane (replaces the old YAML modal) docked right of the
 * Scenario pane, so the YAML can be edited alongside the graph instead of
 * blocking it. Live-syncs one way — GUI edits elsewhere (add a reactor,
 * drag a node) refresh the displayed YAML automatically as long as there's
 * no unsaved edit sitting in the editor — and explicitly the other way:
 * typing here only reaches the graph on Save (or Ctrl+S), so a half-typed
 * edit is never parsed as YAML mid-keystroke.
 */
export function YamlPane() {
  const config = useConfigStore((s) => s.config);
  const originalYaml = useConfigStore((s) => s.originalYaml);
  const fileName = useConfigStore((s) => s.fileName);
  const setConfig = useConfigStore((s) => s.setConfig);
  const closeYamlPane = useLayoutStore((s) => s.closeYamlPane);
  const theme = useThemeStore((s) => s.theme);

  const [value, setValue] = useState("");
  const [baseline, setBaseline] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncWarnings, setSyncWarnings] = useState<string[]>([]);

  const isDirty = value !== baseline;
  // Effects below only re-run when `config`/`originalYaml` identity changes,
  // not on every keystroke — refs let them see the latest edit state anyway.
  const isDirtyRef = useRef(isDirty);
  isDirtyRef.current = isDirty;
  const justSavedRef = useRef(false);

  const refresh = useCallback(() => {
    setSyncError(null);
    // No graph to sync (e.g. Boulder started with no preloaded config): show
    // whatever original YAML there is — possibly "", which mounts an empty
    // but editable pane rather than blocking on a "nothing to edit" error.
    if (config.nodes.length === 0) {
      setValue(originalYaml);
      setBaseline(originalYaml);
      setSyncWarnings([]);
      return;
    }
    // A live graph exists but there's no original YAML to merge it into —
    // this is the only case syncConfig genuinely can't handle.
    if (!originalYaml) {
      setSyncError("No configuration available to edit.");
      return;
    }
    setSyncing(true);
    syncConfig(config, originalYaml)
      .then((resp) => {
        setValue(resp.yaml);
        setBaseline(resp.yaml);
        setSyncWarnings(resp.warnings ?? []);
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err);
        console.error("[YamlPane] syncConfig failed", { message: msg, error: err });
        setSyncError(
          `Failed to sync YAML with current configuration: ${msg}. ` +
            "The displayed YAML may not match the live config.",
        );
        // Do NOT fall back to stale originalYaml — saving it would overwrite GUI edits.
      })
      .finally(() => setSyncing(false));
  }, [config, originalYaml]);

  // Refresh on open, and whenever the config changes elsewhere (add/edit a
  // node, etc.) — but never while there's an unsaved edit sitting in the
  // editor, and not immediately after our own Save (which already set
  // `baseline` to exactly what's on disk, no round-trip needed).
  useEffect(() => {
    if (justSavedRef.current) {
      justSavedRef.current = false;
      return;
    }
    if (isDirtyRef.current) return;
    refresh();
  }, [refresh]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const resp = await parseYaml(value);
      setConfig(resp.config, undefined, value);
      justSavedRef.current = true;
      setBaseline(value);
      // The backend may have just adopted this Save as its preloaded config
      // (if none was set yet) — bump scenarioRevision so RunControl re-checks
      // Run Sweep availability instead of showing stale info.
      void useScenarioStore.getState().refresh();
      toast.success("YAML config updated");
    } catch (err) {
      toast.error(`Invalid YAML: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }, [value, setConfig]);

  const canSave = isDirty && !saving && !syncing && !syncError;

  // Ctrl/Cmd+S saves instead of triggering the browser's "Save Page As".
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (canSave) void handleSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canSave, handleSave]);

  const handleCancel = () => {
    setValue(baseline);
    setSyncError(null);
  };

  const handleClose = () => {
    if (isDirty && !window.confirm("Discard unsaved YAML changes?")) return;
    closeYamlPane();
  };

  const handleDownload = () => {
    const blob = new Blob([value], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName || "config.yaml";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-[calc(100vh-5rem)] flex-col rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between gap-2 border-b border-border p-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FileCode size={16} className="shrink-0 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground truncate">YAML</h2>
        </div>
        <Button onClick={handleClose} variant="ghost" size="icon" aria-label="Close YAML pane">
          <X size={16} />
        </Button>
      </div>

      {syncWarnings.length > 0 && (
        <div
          id="sync-warnings-banner"
          className="px-3 py-2 text-xs bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-800 text-yellow-800 dark:text-yellow-300 space-y-0.5 shrink-0"
        >
          <p className="font-semibold">Sync warnings (non-blocking):</p>
          {syncWarnings.map((w, i) => (
            <p key={i}>{w}</p>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-hidden">
        {syncing ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
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
              theme={theme === "dark" ? "vs-dark" : "light"}
              options={{
                minimap: { enabled: false },
                wordWrap: "on",
                fontSize: 13,
              }}
            />
          </Suspense>
        )}
      </div>

      <div className="flex justify-end gap-2 p-3 border-t border-border shrink-0">
        <Button onClick={handleDownload} variant="muted" size="sm">
          Download
        </Button>
        <Button onClick={handleCancel} disabled={!isDirty} variant="secondary" size="sm">
          Cancel
        </Button>
        <Button
          id="save-config-yaml-edit-btn"
          onClick={() => void handleSave()}
          disabled={!canSave}
          variant="primary"
          size="sm"
          title="Save (Ctrl+S)"
        >
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}
