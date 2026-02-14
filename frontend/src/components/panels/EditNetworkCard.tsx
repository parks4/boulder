import { useState, useCallback, useRef } from "react";
import { useConfigStore } from "@/stores/configStore";
import { uploadConfigFile } from "@/api/configs";
import { AddReactorModal } from "@/components/modals/AddReactorModal";
import { AddMFCModal } from "@/components/modals/AddMFCModal";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

export function EditNetworkCard() {
  const [showAddReactor, setShowAddReactor] = useState(false);
  const [showAddMFC, setShowAddMFC] = useState(false);
  const setConfig = useConfigStore((s) => s.setConfig);
  const config = useConfigStore((s) => s.config);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  return (
    <>
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <h3 className="font-semibold text-sm text-foreground">Edit Network</h3>

        <div className="flex flex-col gap-2">
          <Button
            id="open-reactor-modal"
            onClick={() => setShowAddReactor(true)}
            variant="muted"
            className="w-full"
          >
            + Add Reactor
          </Button>

          <Button
            id="open-mfc-modal"
            onClick={() => setShowAddMFC(true)}
            variant="muted"
            className="w-full"
            disabled={config.nodes.length < 2}
          >
            + Add Connection
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
