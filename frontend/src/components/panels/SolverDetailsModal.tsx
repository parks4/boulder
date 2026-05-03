import { useEffect } from "react";
import { Button } from "@/components/ui/Button";
import {
  KIND_LABELS,
  type SolverKind,
  type SolverMode,
} from "./solverShared";

interface SolverDetailsModalProps {
  open: boolean;
  onClose: () => void;
  mode: SolverMode;
  kind: SolverKind;
  kinds: SolverKind[];
  onKindChange: (newKind: SolverKind) => void;
  rtol: string;
  onRtolChange: (v: string) => void;
  atol: string;
  onAtolChange: (v: string) => void;
  maxSteps: string;
  onMaxStepsChange: (v: string) => void;
  simTime: string;
  onSimTimeChange: (v: string) => void;
  timeStep: string;
  onTimeStepChange: (v: string) => void;
}

export function SolverDetailsModal({
  open,
  onClose,
  mode,
  kind,
  kinds,
  onKindChange,
  rtol,
  onRtolChange,
  atol,
  onAtolChange,
  maxSteps,
  onMaxStepsChange,
  simTime,
  onSimTimeChange,
  timeStep,
  onTimeStepChange,
}: SolverDetailsModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      data-testid="solver-details-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-labelledby="solver-details-title"
        className="w-full max-w-md bg-card border border-border rounded-lg shadow-lg flex flex-col max-h-[90vh]"
      >
        <div className="flex items-center justify-between p-4 border-b border-border shrink-0">
          <h2 id="solver-details-title" className="text-lg font-semibold text-foreground">
            Solver details
          </h2>
          <Button onClick={onClose} variant="ghost" size="icon" className="text-lg" aria-label="Close">
            ×
          </Button>
        </div>

        <div className="p-4 space-y-3 overflow-y-auto">
          <label className="block text-xs text-muted-foreground">
            Kind
            <select
              data-testid="solver-kind-select"
              value={kind}
              onChange={(e) => onKindChange(e.target.value as SolverKind)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
            >
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABELS[k]}
                </option>
              ))}
            </select>
          </label>

          {mode === "steady" && (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <label className="block text-xs text-muted-foreground">
                  rtol
                  <input
                    data-testid="steady-rtol"
                    type="text"
                    value={rtol}
                    onChange={(e) => onRtolChange(e.target.value)}
                    className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
                  />
                </label>
                <label className="block text-xs text-muted-foreground">
                  atol
                  <input
                    data-testid="steady-atol"
                    type="text"
                    value={atol}
                    onChange={(e) => onAtolChange(e.target.value)}
                    className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
                  />
                </label>
              </div>
              <label className="block text-xs text-muted-foreground">
                max_steps
                <input
                  data-testid="steady-max-steps"
                  type="number"
                  value={maxSteps}
                  onChange={(e) => onMaxStepsChange(e.target.value)}
                  className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
                  min="1"
                />
              </label>
            </div>
          )}

          {mode === "transient" && (
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs text-muted-foreground">
                Time (s)
                <input
                  data-testid="transient-time"
                  type="number"
                  value={simTime}
                  onChange={(e) => onSimTimeChange(e.target.value)}
                  className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
                  min="0.1"
                  step="0.1"
                />
              </label>
              <label className="block text-xs text-muted-foreground">
                Step (s)
                <input
                  data-testid="transient-step"
                  type="number"
                  value={timeStep}
                  onChange={(e) => onTimeStepChange(e.target.value)}
                  className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
                  min="0.001"
                  step="0.001"
                />
              </label>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-border shrink-0">
          <Button onClick={onClose} variant="primary" size="sm">
            Done
          </Button>
        </div>
      </div>
    </div>
  );
}
