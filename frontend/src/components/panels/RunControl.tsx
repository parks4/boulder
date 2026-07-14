import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { getSweepInfo, getSweepStatus, startSweep, type SweepInfo } from "@/api/sweep";
import { useScenarioStore } from "@/stores/scenarioStore";
import { AddScenarioModal } from "@/components/modals/AddScenarioModal";
import { ScenarioYamlEditorModal } from "@/components/modals/ScenarioYamlEditorModal";

type RunMode = "sim" | "force_sim" | "sweep";

interface RunControlProps {
  onRunSimulation: (force?: boolean) => void;
  isRunning: boolean;
  runDisabled: boolean;
}

/**
 * GitHub-merge-style split button: a primary action ("Run Simulation") with a
 * caret dropdown to switch the action to "Run Sweep". Run Sweep is only
 * selectable when the config declares a runnable ``sweeps:`` block (the reason
 * is shown in the menu and on the button). Running a sweep streams progress and
 * refreshes the Scenario Pane on completion.
 */
export function RunControl({ onRunSimulation, isRunning, runDisabled }: RunControlProps) {
  const [runMode, setRunMode] = useState<RunMode>("sim");
  const [menuOpen, setMenuOpen] = useState(false);
  const [sweep, setSweep] = useState<SweepInfo | null>(null);
  const [sweeping, setSweeping] = useState(false);
  const [progress, setProgress] = useState<{ current: number; total: number }>({
    current: 0,
    total: 0,
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const appliedDefault = useRef(false);
  const appliedAutorun = useRef(false);
  const refreshScenarios = useScenarioStore((s) => s.refresh);
  const [addScenarioOpen, setAddScenarioOpen] = useState(false);
  const [editingScenarioId, setEditingScenarioId] = useState<string | null>(null);

  const loadSweepInfo = useCallback(() => {
    getSweepInfo()
      .then((info) => {
        setSweep(info);
        // `--sweep` GUI mode: default the split button to Run Sweep (once).
        if (!appliedDefault.current && info.default && info.can_run) {
          appliedDefault.current = true;
          setRunMode("sweep");
        }
      })
      .catch(() => setSweep(null));
  }, []);

  useEffect(() => {
    loadSweepInfo();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadSweepInfo]);

  const canSweep = Boolean(sweep?.can_run);
  // If sweep is unavailable, fall back to simulation (force_sim is kept as-is).
  const effectiveMode: RunMode =
    runMode === "sweep" && canSweep
      ? "sweep"
      : runMode === "force_sim"
        ? "force_sim"
        : "sim";

  const handleRunSweep = useCallback(() => {
    setSweeping(true);
    setProgress({ current: 0, total: sweep?.n_scenarios ?? 0 });
    startSweep()
      .then(() => {
        pollRef.current = setInterval(() => {
          getSweepStatus()
            .then((st) => {
              if (st.status === "running") {
                setProgress({ current: st.current ?? 0, total: st.total ?? 0 });
              } else {
                if (pollRef.current) clearInterval(pollRef.current);
                setSweeping(false);
                if (st.status === "done") {
                  toast.success("Sweep complete — scenarios updated");
                  void refreshScenarios();
                  loadSweepInfo();
                } else {
                  toast.error(`Sweep failed: ${st.message ?? "unknown error"}`);
                }
              }
            })
            .catch(() => {
              if (pollRef.current) clearInterval(pollRef.current);
              setSweeping(false);
            });
        }, 1000);
      })
      .catch((e) => {
        setSweeping(false);
        toast.error(e instanceof Error ? e.message : String(e));
      });
  }, [sweep, refreshScenarios, loadSweepInfo]);

  // `--run`: auto-start the run once, as soon as it is actually runnable.
  useEffect(() => {
    if (!sweep?.autorun || appliedAutorun.current) return;
    if (effectiveMode === "sweep") {
      if (!canSweep || sweeping || isRunning) return;
      appliedAutorun.current = true;
      handleRunSweep();
    } else if (effectiveMode === "force_sim") {
      if (runDisabled) return;
      appliedAutorun.current = true;
      onRunSimulation(true);
    } else {
      if (runDisabled) return; // wait until the config is loaded and idle
      appliedAutorun.current = true;
      onRunSimulation(false);
    }
  }, [
    sweep,
    effectiveMode,
    canSweep,
    sweeping,
    isRunning,
    runDisabled,
    handleRunSweep,
    onRunSimulation,
  ]);

  const primaryLabel =
    effectiveMode === "sweep"
      ? sweeping
        ? `Sweeping… ${progress.current}/${progress.total}`
        : `Run Sweep (${sweep?.n_scenarios ?? 0} scenarios)`
      : effectiveMode === "force_sim"
        ? isRunning
          ? "Running…"
          : "Force Run"
        : isRunning
          ? "Running…"
          : "Run Simulation (Ctrl+Enter)";

  const primaryDisabled =
    effectiveMode === "sweep" ? sweeping || isRunning || !canSweep : runDisabled;
  const variant = primaryDisabled ? "muted" : "success";

  const onPrimary = () => {
    if (effectiveMode === "sweep") handleRunSweep();
    else onRunSimulation(effectiveMode === "force_sim");
  };

  return (
    <div className="relative w-full">
      <div className="flex w-full">
        <Button
          id="run-primary"
          onClick={onPrimary}
          disabled={primaryDisabled}
          variant={variant}
          className="flex-1 rounded-r-none"
        >
          {primaryLabel}
        </Button>
        <Button
          id="run-mode-caret"
          onClick={() => setMenuOpen((o) => !o)}
          disabled={isRunning || sweeping}
          variant={variant}
          className="rounded-l-none border-l border-black/15 px-2"
          aria-label="Choose run action"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <ChevronDown size={16} />
        </Button>
      </div>

      {menuOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
          <div
            role="menu"
            className="absolute right-0 z-20 mt-1 w-72 rounded-md border border-border bg-card shadow-lg overflow-hidden"
          >
            <RunModeItem
              active={effectiveMode === "sim"}
              title="Run Simulation"
              description="Solve the single reactor as configured."
              onClick={() => {
                setRunMode("sim");
                setMenuOpen(false);
              }}
            />
            <RunModeItem
              active={effectiveMode === "force_sim"}
              title="Force Run"
              description="Solve ignoring cache"
              onClick={() => {
                setRunMode("force_sim");
                setMenuOpen(false);
              }}
            />
            <div className="border-t border-border" />
            <RunModeItem
              active={effectiveMode === "sweep"}
              title="Run Sweep"
              description={sweep?.reason ?? "No sweep in this config"}
              disabled={!canSweep}
              onClick={() => {
                setRunMode("sweep");
                setMenuOpen(false);
              }}
            />
            <div className="border-t border-border" />
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                setAddScenarioOpen(true);
              }}
              className="w-full text-left px-3 py-2.5 flex gap-2 hover:bg-muted cursor-pointer"
            >
              <span className="w-4 shrink-0 pt-0.5 text-primary">
                <Plus size={14} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-foreground">
                  Add Scenario…
                </span>
                <span className="block text-xs text-muted-foreground">
                  Create a new scenario overlay and edit its YAML.
                </span>
              </span>
            </button>
          </div>
        </>
      )}

      <AddScenarioModal
        open={addScenarioOpen}
        onClose={() => setAddScenarioOpen(false)}
        onCreated={(id) => setEditingScenarioId(id)}
      />
      <ScenarioYamlEditorModal
        scenarioId={editingScenarioId}
        onClose={() => setEditingScenarioId(null)}
        onSaved={() => void refreshScenarios()}
      />
    </div>
  );
}

function RunModeItem({
  active,
  title,
  description,
  disabled,
  onClick,
}: {
  active: boolean;
  title: string;
  description: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={active}
      disabled={disabled}
      onClick={onClick}
      className={[
        "w-full text-left px-3 py-2.5 flex gap-2",
        disabled
          ? "opacity-50 cursor-not-allowed"
          : "hover:bg-muted cursor-pointer",
      ].join(" ")}
    >
      <span className="w-4 shrink-0 pt-0.5 text-primary">
        {active && <Check size={14} />}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        <span className="block text-xs text-muted-foreground">{description}</span>
      </span>
    </button>
  );
}
