import { useState } from "react";
import { cn } from "@/lib/cn";
import { useConfigStore } from "@/stores/configStore";
import { celsiusToKelvin } from "@/lib/units";
import { toast } from "sonner";

interface Props {
  open: boolean;
  onClose: () => void;
}

const REACTOR_TYPES = [
  "IdealGasReactor",
  "IdealGasConstPressureReactor",
  "Reservoir",
];

export function AddReactorModal({ open, onClose }: Props) {
  const addNode = useConfigStore((s) => s.addNode);
  const [id, setId] = useState("");
  const [type, setType] = useState(REACTOR_TYPES[0]);
  const [temp, setTemp] = useState("1000");
  const [pressure, setPressure] = useState("101325");
  const [composition, setComposition] = useState("O2:1,N2:3.76");

  if (!open) return null;

  const handleSubmit = () => {
    const trimmedId = id.trim();
    if (!trimmedId) {
      toast.error("Reactor ID is required");
      return;
    }
    try {
      addNode({
        id: trimmedId,
        type,
        properties: {
          temperature: celsiusToKelvin(parseFloat(temp) || 0),
          pressure: parseFloat(pressure) || 101325,
          composition: composition.trim() || undefined,
        },
      });
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
          <select
            id="reactor-type"
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
          >
            {REACTOR_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>

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
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md bg-secondary text-secondary-foreground hover:opacity-80"
          >
            Cancel
          </button>
          <button
            id="add-reactor"
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
