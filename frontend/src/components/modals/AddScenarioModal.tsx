import { useState } from "react";
import { useScenarioStore } from "@/stores/scenarioStore";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Called after the scenario is created, so the caller can open its editor. */
  onCreated: (scenarioId: string) => void;
}

const BLANK = "__blank__";

/**
 * "+ Add Scenario" — the entry point for authoring a scenario: pick an id
 * and, optionally, an existing scenario to clone as a starting point. The
 * new overlay opens in the scoped editor immediately so the user edits it
 * right away.
 */
export function AddScenarioModal({ open, onClose, onCreated }: Props) {
  const scenarios = useScenarioStore((s) => s.scenarios);
  const authoredIds = useScenarioStore((s) => s.authoredIds);
  const createScenario = useScenarioStore((s) => s.createScenario);
  const [id, setId] = useState("");
  const [baseId, setBaseId] = useState(BLANK);
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const handleSubmit = async () => {
    const trimmed = id.trim();
    if (!trimmed) {
      toast.error("Scenario id is required");
      return;
    }
    if (!/^[A-Za-z0-9_-]+$/.test(trimmed)) {
      toast.error("Scenario id must use letters, digits, '_' or '-' only");
      return;
    }
    setSubmitting(true);
    try {
      await createScenario(trimmed, baseId === BLANK ? undefined : baseId);
      toast.success(`Scenario "${trimmed}" created`);
      onCreated(trimmed);
      setId("");
      setBaseId(BLANK);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      id="add-scenario-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md bg-card border border-border rounded-lg shadow-lg p-6 space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Add Scenario</h2>

        <label className="block text-xs text-muted-foreground">
          Scenario id
          <input
            id="scenario-id"
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="e.g. C1T"
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleSubmit();
            }}
          />
        </label>

        <label className="block text-xs text-muted-foreground">
          Start from
          <select
            id="scenario-base"
            value={baseId}
            onChange={(e) => setBaseId(e.target.value)}
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input border border-border text-foreground"
          >
            <option value={BLANK}>Blank overlay</option>
            {/* All scenarios currently in the config, not just ones a sweep has
                already computed — otherwise a scenario created (or edited) since
                the last sweep can't be used as a clone base. */}
            {authoredIds.map((sid) => (
              <option key={sid} value={sid}>
                Clone of {scenarios.find((s) => s.id === sid)?.label || sid}
              </option>
            ))}
          </select>
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <Button onClick={onClose} variant="secondary" size="sm">
            Cancel
          </Button>
          <Button
            id="add-scenario-submit"
            onClick={() => void handleSubmit()}
            disabled={submitting}
            variant="primary"
            size="sm"
          >
            {submitting ? "Creating…" : "Create"}
          </Button>
        </div>
      </div>
    </div>
  );
}
