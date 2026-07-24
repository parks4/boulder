import { useCallback, useRef } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useScenarioStore } from "@/stores/scenarioStore";
import { uploadConfigFile } from "@/api/configs";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

interface Props {
  onEditYaml: () => void;
}

/**
 * Network-level actions: which config is loaded, and how to change it
 * wholesale (edit the YAML directly, or replace it with an upload).
 * Adding individual reactors/connections happens per-stage — see StageCard
 * and right-click on the graph — since they belong to a specific stage.
 */
export function NetworkCard({ onEditYaml }: Props) {
  const setConfig = useConfigStore((s) => s.setConfig);
  const fileName = useConfigStore((s) => s.fileName);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      try {
        const resp = await uploadConfigFile(file);
        setConfig(resp.config, resp.filename, resp.yaml);
        // The backend may have just adopted this upload as its preloaded
        // config (if none was set yet) — bump scenarioRevision so RunControl
        // re-checks Run Sweep availability instead of showing stale info.
        void useScenarioStore.getState().refresh();
        toast.success(`Config uploaded: ${resp.filename}`);
      } catch (err) {
        toast.error(`Upload failed: ${err instanceof Error ? err.message : String(err)}`);
      }
      e.target.value = "";
    },
    [setConfig],
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 className="font-semibold text-sm text-foreground">Network</h3>

      <p
        id="network-file-name"
        className="text-sm font-mono text-foreground truncate"
        title={fileName ?? "untitled.yaml"}
      >
        {fileName ?? "untitled.yaml"}
      </p>

      <div className="grid grid-cols-2 gap-2">
        <Button id="edit-yaml-btn" onClick={onEditYaml} variant="muted" className="w-full">
          Edit YAML
        </Button>
        <Button
          id="config-upload-btn"
          onClick={() => fileInputRef.current?.click()}
          variant="muted"
          className="w-full"
        >
          Upload Config
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".yaml,.yml,.py"
          onChange={handleUpload}
          className="hidden"
        />
      </div>
    </div>
  );
}
