import { useState, useCallback } from "react";
import { cn } from "@/lib/cn";
import { useConfigStore } from "@/stores/configStore";
import { uploadConfigFile, fetchDefaultConfig } from "@/api/configs";
import { AddReactorModal } from "@/components/modals/AddReactorModal";
import { AddMFCModal } from "@/components/modals/AddMFCModal";
import { toast } from "sonner";

export function EditNetworkCard() {
  const [showAddReactor, setShowAddReactor] = useState(false);
  const [showAddMFC, setShowAddMFC] = useState(false);
  const setConfig = useConfigStore((s) => s.setConfig);
  const config = useConfigStore((s) => s.config);

  const handleUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      try {
        const resp = await uploadConfigFile(file);
        setConfig(resp.config, resp.filename, resp.yaml);
        toast.success(`Config uploaded: ${resp.filename}`);
      } catch (err) {
        toast.error(`Upload failed: ${err instanceof Error ? err.message : String(err)}`);
      }
      e.target.value = "";
    },
    [setConfig],
  );

  const handleLoadDefault = useCallback(async () => {
    try {
      const resp = await fetchDefaultConfig();
      setConfig(resp.config, "default.yaml", resp.yaml);
      toast.success("Default config loaded");
    } catch (err) {
      toast.error(`Failed to load default: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [setConfig]);

  return (
    <>
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <h3 className="font-semibold text-sm text-foreground">Edit Network</h3>

        <div className="flex flex-col gap-2">
          <button
            id="open-reactor-modal"
            onClick={() => setShowAddReactor(true)}
            className={cn(
              "w-full px-3 py-2 text-sm rounded-md",
              "bg-primary text-primary-foreground hover:opacity-90 transition-opacity",
            )}
          >
            + Add Reactor
          </button>

          <button
            id="open-mfc-modal"
            onClick={() => setShowAddMFC(true)}
            className={cn(
              "w-full px-3 py-2 text-sm rounded-md",
              "bg-secondary text-secondary-foreground hover:opacity-80 transition-opacity",
            )}
            disabled={config.nodes.length < 2}
          >
            + Add Connection
          </button>

          <button
            onClick={handleLoadDefault}
            className={cn(
              "w-full px-3 py-2 text-sm rounded-md",
              "bg-secondary text-secondary-foreground hover:opacity-80 transition-opacity",
            )}
          >
            Load Default
          </button>
        </div>

        <div id="config-upload-area" className="mt-2">
          <label className="block">
            <span className="text-xs text-muted-foreground">
              Upload config (.yaml, .py)
            </span>
            <input
              type="file"
              accept=".yaml,.yml,.py"
              onChange={handleUpload}
              className="block w-full text-xs mt-1 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-xs file:bg-primary file:text-primary-foreground"
            />
          </label>
        </div>
      </div>

      <AddReactorModal
        open={showAddReactor}
        onClose={() => setShowAddReactor(false)}
      />
      <AddMFCModal
        open={showAddMFC}
        onClose={() => setShowAddMFC(false)}
      />
    </>
  );
}
