import { useMemo, useState } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useKinds } from "@/hooks/useKinds";
import { celsiusToKelvin } from "@/lib/units";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { toast } from "sonner";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Stage to add the reactor to (e.g. right-clicked a stage box). */
  defaultGroup?: string | null;
}

// Used only until /api/ui/kinds resolves, or if that fetch fails.
const FALLBACK_REACTOR_TYPES = [
  "IdealGasReactor",
  "IdealGasConstPressureReactor",
  "Reservoir",
];

export function AddReactorModal({ open, onClose, defaultGroup }: Props) {
  const addNode = useConfigStore((s) => s.addNode);
  const nodes = useConfigStore((s) => s.config.nodes);
  const connections = useConfigStore((s) => s.config.connections);
  const { reactors } = useKinds();
  const reactorTypes = useMemo(
    () => (reactors.length > 0 ? reactors.map((r) => r.kind) : FALLBACK_REACTOR_TYPES),
    [reactors],
  );

  // Only offer a stage picker when the config actually has more than one —
  // otherwise the new reactor unambiguously belongs to the single stage.
  const stages = useMemo(() => {
    const groups = new Set(
      [...nodes.map((n) => n.group), ...connections.map((c) => c.group)].filter(
        (g): g is string => typeof g === "string" && g.length > 0,
      ),
    );
    return [...groups].sort();
  }, [nodes, connections]);

  const [id, setId] = useState("");
  const [type, setType] = useState(reactorTypes[0]);
  const [group, setGroup] = useState(defaultGroup ?? "");
  const [temp, setTemp] = useState("1000");
  const [pressure, setPressure] = useState("101325");
  const [composition, setComposition] = useState("O2:1,N2:3.76");

  // Falls back to the first available type if the selected one disappears —
  // e.g. `type` was set from the fallback list before /api/ui/kinds resolved.
  // Derived at render time rather than synced via effect.
  const effectiveType = reactorTypes.includes(type) ? type : reactorTypes[0];

  if (!open) return null;

  const selectedDoc = reactors.find((r) => r.kind === effectiveType);

  const handleSubmit = () => {
    const trimmedId = id.trim();
    if (!trimmedId) {
      toast.error("Reactor ID is required");
      return;
    }
    try {
      addNode(
        {
          id: trimmedId,
          type: effectiveType,
          properties: {
            temperature: celsiusToKelvin(parseFloat(temp) || 0),
            pressure: parseFloat(pressure) || 101325,
            composition: composition.trim() || undefined,
          },
        },
        group || undefined,
      );
      toast.success(`Reactor "${trimmedId}" added`);
      // Reset & close
      setId("");
      setTemp("1000");
      setPressure("101325");
      setComposition("O2:1,N2:3.76");
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div
      id="add-reactor-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-md bg-card border border-border rounded-lg shadow-lg p-6 space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Add Reactor</h2>

        <label className="block text-xs text-muted-foreground">
          Reactor ID
          <input
            id="reactor-id"
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
              id="reactor-type"
              value={effectiveType}
              onChange={(e) => setType(e.target.value)}
              className="block w-full px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            >
              {reactorTypes.map((t) => (
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
              id="reactor-stage"
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
            Temperature (°C)
            <input
              id="reactor-temp"
              type="number"
              value={temp}
              onChange={(e) => setTemp(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            Pressure (Pa)
            <input
              id="reactor-pressure"
              type="number"
              value={pressure}
              onChange={(e) => setPressure(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            />
          </label>
        </div>

        <label className="block text-xs text-muted-foreground">
          Composition
          <input
            id="reactor-composition"
            value={composition}
            onChange={(e) => setComposition(e.target.value)}
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            placeholder="CH4:1,O2:2,N2:7.52"
          />
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <Button onClick={onClose} variant="secondary" size="sm">
            Cancel
          </Button>
          <Button id="add-reactor" onClick={handleSubmit} variant="primary" size="sm">
            Add
          </Button>
        </div>
      </div>
    </div>
  );
}
