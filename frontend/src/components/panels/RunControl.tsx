import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { getSweepInfo, type SweepInfo } from "@/api/sweep";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useSweepRunStore } from "@/stores/sweepStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { useShortcutNudge } from "@/hooks/useShortcutNudge";
import { useSimulationRunPhase, useSweepRunPhase } from "@/hooks/useRunStatus";
import { AddScenarioModal } from "@/components/modals/AddScenarioModal";

type RunMode = "sim" | "force_sim" | "sweep";

interface RunControlProps {
  onRunSimulation: (force?: boolean) => void;
  /** Request that the in-flight single run stop (see api/simulations.ts's stopSimulation). */
  onStopSimulation: () => void;
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
export function RunControl({
  onRunSimulation,
  onStopSimulation,
  isRunning,
  runDisabled,
}: RunControlProps) {
  const [runMode, setRunMode] = useState<RunMode>("sim");
  const [menuOpen, setMenuOpen] = useState(false);
  // The menu portals to `document.body` (see below) so the sidebar's
  // `overflow-y-auto` can't clip it -- position is computed from this
  // anchor's rect each time the menu opens.
  const anchorRef = useRef<HTMLDivElement>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null);
  const [sweep, setSweep] = useState<SweepInfo | null>(null);
  const sweeping = useSweepRunStore((s) => s.sweeping);
  const progress = useSweepRunStore((s) => s.progress);
  const runSweepJob = useSweepRunStore((s) => s.run);
  const stopSweepJob = useSweepRunStore((s) => s.stop);
  const simPhase = useSimulationRunPhase();
  const sweepPhase = useSweepRunPhase();
  const appliedDefault = useRef(false);
  const appliedAutorun = useRef(false);
  const scenarioRevision = useScenarioStore((s) => s.revision);
  const authoredScenarioCount = useScenarioStore((s) => s.authoredIds.length);
  const [addScenarioOpen, setAddScenarioOpen] = useState(false);
  const openScenarioYamlEditor = useLayoutStore((s) => s.openScenarioYamlEditor);
  const notifyShortcutUsage = useShortcutNudge();

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

  // Re-fetch whenever a scenario is added/edited/renamed/deleted elsewhere
  // (scenarioRevision bumps on every scenarioStore.refresh()) — otherwise
  // "Run N scenarios" silently goes stale after any Scenario Pane action.
  useEffect(() => {
    loadSweepInfo();
  }, [loadSweepInfo, scenarioRevision]);

  // Open: compute the menu's viewport position from the anchor now (not on
  // every render) so it tracks wherever the split button actually is,
  // including when the sidebar has been scrolled.
  const openMenu = useCallback(() => {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (rect) {
      setMenuPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
    }
    setMenuOpen(true);
  }, []);

  // Close (rather than reposition) on scroll/resize elsewhere on the page --
  // simplest robust fix for the menu drifting from its anchor; reopening
  // recomputes the position fresh via openMenu above.
  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [menuOpen]);

  // `sweep` reflects the config's startup snapshot (scenario authoring is
  // in-memory now — see scenarioStore.ts's `overlays`), so a scenario
  // created this session wouldn't otherwise be counted until a page reload.
  // `authoredScenarioCount` covers that; `sweep?.can_run` still covers a
  // host-defined `sweep:` block with no scenario overlays at all.
  const canSweep = Boolean(sweep?.can_run) || authoredScenarioCount > 0;
  const nScenarios = Math.max(sweep?.n_scenarios ?? 0, authoredScenarioCount);
  // If sweep is unavailable, fall back to simulation (force_sim is kept as-is).
  const effectiveMode: RunMode =
    runMode === "sweep" && canSweep
      ? "sweep"
      : runMode === "force_sim"
        ? "force_sim"
        : "sim";

  // loadSweepInfo() re-fetches automatically once the sweep finishes: it
  // depends on scenarioRevision (above), which the shared sweep store bumps
  // via scenarioStore.refresh() on completion -- no separate wiring needed
  // here, and it stays in sync even when a sweep is started elsewhere.
  const handleRunSweep = useCallback(() => {
    runSweepJob({ total: nScenarios });
  }, [runSweepJob, nScenarios]);

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

  // Which phase governs the primary button depends on which action it
  // currently performs -- "sweep" mode tracks the sweep job, "sim"/
  // "force_sim" track the plain single-run store, regardless of which one
  // is actually in flight (the two are mutually exclusive by the disabled
  // guards below).
  const phase = effectiveMode === "sweep" ? sweepPhase : simPhase;

  const primaryLabel =
    effectiveMode === "sweep"
      ? phase === "idle"
        ? // A `while:` chain's length is only known once its condition
          // trips, so the server reports 0 -- no count to show.
          nScenarios > 0
          ? `Run Sweep (${nScenarios} scenarios)`
          : "Run Sweep"
        : phase === "stopping"
          ? "Stopping Sweep…"
          : `Stop Sweep (${progress.current}/${progress.total})`
      : phase === "idle"
        ? effectiveMode === "force_sim"
          ? "Force Run"
          : "Run Simulation (Ctrl+Enter)"
        : phase === "stopping"
          ? "Stopping Simulation…"
          : "Stop Simulation";

  // Stopping is cooperative and can only take effect at the next checkpoint
  // (a stage boundary for a single run, a scenario boundary for a sweep) --
  // this doesn't change the disabled state (the button already shows
  // "Stopping…" and is inert), it just explains the wait instead of letting
  // it read as a hang.
  const primaryTitle = phase === "stopping" ? "Will stop at the next checkpoint" : undefined;

  const primaryDisabled =
    phase === "stopping"
      ? true
      : phase === "running"
        ? false
        : effectiveMode === "sweep"
          ? sweeping || isRunning || !canSweep
          : runDisabled;
  const variant =
    phase === "stopping" ? "warning" : phase === "running" ? "destructive" : primaryDisabled ? "muted" : "success";

  const onPrimary = () => {
    if (phase === "running") {
      if (effectiveMode === "sweep") stopSweepJob();
      else onStopSimulation();
      return;
    }
    if (effectiveMode === "sweep") handleRunSweep();
    else {
      // Ctrl+Enter (see AppShell's keydown handler) always runs the plain
      // "sim" action regardless of the split button's mode — only nudge when
      // a click here does the exact same thing the shortcut would.
      if (effectiveMode === "sim") notifyShortcutUsage("run-simulation", "Ctrl+Enter");
      onRunSimulation(effectiveMode === "force_sim");
    }
  };

  return (
    <div className="relative w-full" ref={anchorRef}>
      <div className="flex w-full">
        <Button
          id="run-primary"
          onClick={onPrimary}
          disabled={primaryDisabled}
          title={primaryTitle}
          variant={variant}
          className="flex-1 rounded-r-none"
        >
          {primaryLabel}
        </Button>
        <Button
          id="run-mode-caret"
          onClick={() => (menuOpen ? setMenuOpen(false) : openMenu())}
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

      {menuOpen && menuPos && createPortal(
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
          <div
            role="menu"
            style={{ position: "fixed", top: menuPos.top, right: menuPos.right }}
            className="z-[41] w-72 rounded-md border border-border bg-card shadow-lg overflow-hidden"
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
        </>,
        document.body,
      )}

      <AddScenarioModal
        open={addScenarioOpen}
        onClose={() => setAddScenarioOpen(false)}
        onCreated={(id) => openScenarioYamlEditor(id)}
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
