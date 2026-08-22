import { useCallback, useRef } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { uploadConfigFile } from "@/api/configs";
import { BASELINE_SCENARIO_ID } from "@/api/scenarios";
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
  const activeScenarioId = useScenarioStore((s) => s.activeId);
  const openScenarioYamlEditor = useLayoutStore((s) => s.openScenarioYamlEditor);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // BASELINE is the unmodified base config itself, so it edits the same way
  // as no scenario being active; any other active scenario edits its own
  // overlay subtree instead of the whole file.
  const editingScenario =
    activeScenarioId && activeScenarioId !== BASELINE_SCENARIO_ID
      ? activeScenarioId
      : null;
  const handleEditYaml = () => {
    if (editingScenario) openScenarioYamlEditor(editingScenario);
    else onEditYaml();
  };

  const handleUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      try {
        const resp = await uploadConfigFile(file);
        setConfig(resp.config, resp.filename, resp.yaml);
        // A whole new network was just adopted server-side — drop this
        // session's scenario overlays (they belonged to the previous file)
        // and re-seed from the new config's own `scenarios:` block.
        void useScenarioStore.getState().resetForNewConfig();
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
        <Button
          id="edit-yaml-btn"
          onClick={handleEditYaml}
          variant="muted"
          className="w-full truncate"
          title={
            editingScenario
              ? `Edit this scenario's overlay only (${editingScenario})`
              : "Edit the full base config"
          }
        >
          {editingScenario ? `Edit YAML (${editingScenario})` : "Edit YAML"}
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
