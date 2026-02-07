import { useState, useEffect, lazy, Suspense } from "react";
import { useConfigStore } from "@/stores/configStore";
import { parseYaml, exportConfig } from "@/api/configs";
import { toast } from "sonner";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));

interface Props {
  open: boolean;
  onClose: () => void;
}

export function YAMLEditorModal({ open, onClose }: Props) {
  const { config, originalYaml, setConfig } = useConfigStore();
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);

  // Sync editor content when modal opens or config changes
  useEffect(() => {
    if (!open) return;
    // Show stored YAML immediately so the editor is never empty
    setValue(originalYaml);
    // Then fetch the freshest YAML export from the backend
    if (config.nodes.length > 0) {
      exportConfig(config)
        .then((resp) => setValue(resp.yaml))
        .catch(() => {
          /* keep originalYaml on failure */
        });
    }
  }, [open, config, originalYaml]);

  if (!open) return null;

  const handleSave = async () => {
    setLoading(true);
    try {
      const resp = await parseYaml(value);
      setConfig(resp.config, undefined, value);
      toast.success("YAML config updated");
      onClose();
    } catch (err) {
      toast.error(
        `Invalid YAML: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setLoading(false);
    }
  };

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
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground text-lg"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-hidden">
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
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-border">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md bg-secondary text-secondary-foreground hover:opacity-80"
          >
            Cancel
          </button>
          <button
            id="save-config-yaml-edit-btn"
            onClick={handleSave}
            disabled={loading}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
