import { useMemo, useState } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useKinds } from "@/hooks/useKinds";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { toast } from "sonner";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Stage to add the connection to (e.g. right-clicked a stage box). */
  defaultGroup?: string | null;
  /** Pre-fill the source node (e.g. right-clicked a reactor). */
  defaultSource?: string;
}

// Used only until /api/ui/kinds resolves, or if that fetch fails.
const FALLBACK_CONNECTION_TYPES = ["MassFlowController", "Valve", "Wall"];

export function AddMFCModal({ open, onClose, defaultGroup, defaultSource }: Props) {
  const addConnection = useConfigStore((s) => s.addConnection);
  const nodes = useConfigStore((s) => s.config.nodes);
  const connections = useConfigStore((s) => s.config.connections);
  const { connections: connectionKinds } = useKinds();
  const connectionTypes = useMemo(
    () =>
      connectionKinds.length > 0
        ? connectionKinds.map((c) => c.kind)
        : FALLBACK_CONNECTION_TYPES,
    [connectionKinds],
  );

  const stages = useMemo(() => {
    const groups = new Set(
      [...nodes.map((n) => n.group), ...connections.map((c) => c.group)].filter(
        (g): g is string => typeof g === "string" && g.length > 0,
      ),
    );
    return [...groups].sort();
  }, [nodes, connections]);

  const [id, setId] = useState("");
  const [type, setType] = useState(connectionTypes[0]);
  const [group, setGroup] = useState(defaultGroup ?? "");
  const [source, setSource] = useState(defaultSource ?? "");
  const [target, setTarget] = useState("");
  const [flowRate, setFlowRate] = useState("0.001");

  // Falls back to the first available type if the selected one disappears —
  // e.g. `type` was set from the fallback list before /api/ui/kinds resolved.
  // Derived at render time rather than synced via effect.
  const effectiveType = connectionTypes.includes(type) ? type : connectionTypes[0];

  if (!open) return null;

  const selectedDoc = connectionKinds.find((c) => c.kind === effectiveType);

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
      addConnection(
        {
          id: trimmedId,
          type: effectiveType,
          source,
          target,
          properties: {
            mass_flow_rate: parseFloat(flowRate) || 0.001,
          },
        },
        group || undefined,
      );
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
          <div className="flex items-center gap-1.5 mt-1">
            <select
              value={effectiveType}
              onChange={(e) => setType(e.target.value)}
              className="block w-full px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            >
              {connectionTypes.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
            {selectedDoc?.doc_url && (
              <Tooltip
                content={
                  <span className="block space-y-1">
                    <span className="block">{selectedDoc.description}</span>
                    <a
                      href={selectedDoc.doc_url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline text-primary"
                    >
                      Cantera docs
                    </a>
                  </span>
                }
              >
                <span
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted-foreground cursor-help"
                  aria-label={`About ${effectiveType}`}
                >
                  ⓘ
                </span>
              </Tooltip>
            )}
          </div>
        </label>

        {stages.length > 1 && (
          <label className="block text-xs text-muted-foreground">
            Stage
            <select
              id="mfc-stage"
              value={group}
              onChange={(e) => setGroup(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            >
              <option value="">Auto</option>
              {stages.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}

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
          <Button onClick={onClose} variant="secondary" size="sm">
            Cancel
          </Button>
          <Button id="add-mfc" onClick={handleSubmit} variant="primary" size="sm">
            Add
          </Button>
        </div>
      </div>
    </div>
  );
}
