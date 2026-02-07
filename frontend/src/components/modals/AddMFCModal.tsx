import { useState } from "react";
import { useConfigStore } from "@/stores/configStore";
import { toast } from "sonner";

interface Props {
  open: boolean;
  onClose: () => void;
}

const CONNECTION_TYPES = ["MassFlowController", "Valve", "Wall"];

export function AddMFCModal({ open, onClose }: Props) {
  const addConnection = useConfigStore((s) => s.addConnection);
  const nodes = useConfigStore((s) => s.config.nodes);
  const [id, setId] = useState("");
  const [type, setType] = useState(CONNECTION_TYPES[0]);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [flowRate, setFlowRate] = useState("0.001");

  if (!open) return null;

  const handleSubmit = () => {
    const trimmedId = id.trim();
    if (!trimmedId) {
      toast.error("Connection ID is required");
      return;
    }
    if (!source || !target) {
      toast.error("Source and target are required");
      return;
    }
    if (source === target) {
      toast.error("Source and target must be different");
      return;
    }
    try {
      addConnection({
        id: trimmedId,
        type,
        source,
        target,
        properties: {
          mass_flow_rate: parseFloat(flowRate) || 0.001,
        },
      });
      toast.success(`Connection "${trimmedId}" added`);
      setId("");
      setFlowRate("0.001");
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div
      id="add-mfc-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-md bg-card border border-border rounded-lg shadow-lg p-6 space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Add Connection</h2>

        <label className="block text-xs text-muted-foreground">
          Connection ID
          <input
            id="mfc-id"
            value={id}
            onChange={(e) => setId(e.target.value)}
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            autoFocus
          />
        </label>

        <label className="block text-xs text-muted-foreground">
          Type
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
          >
            {CONNECTION_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs text-muted-foreground">
            Source
            <select
              id="mfc-source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            >
              <option value="">Select...</option>
              {nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.id}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-muted-foreground">
            Target
            <select
              id="mfc-target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            >
              <option value="">Select...</option>
              {nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.id}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="block text-xs text-muted-foreground">
          Mass Flow Rate (kg/s)
          <input
            id="mfc-flow-rate"
            type="number"
            value={flowRate}
            onChange={(e) => setFlowRate(e.target.value)}
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            step="0.001"
          />
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md bg-secondary text-secondary-foreground hover:opacity-80"
          >
            Cancel
          </button>
          <button
            id="add-mfc"
            onClick={handleSubmit}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
