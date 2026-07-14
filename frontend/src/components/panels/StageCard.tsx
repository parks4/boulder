import { useMemo } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useAddEntityModalStore } from "@/stores/addEntityModalStore";
import { useSolverDetailsStore } from "@/stores/solverDetailsStore";
import { Button } from "@/components/ui/Button";
import { KIND_LABELS, type SolverKind } from "./solverShared";

interface Props {
  stageId: string;
}

/**
 * Shown in place of the properties panel when a stage (Cytoscape compound
 * group box) is selected. Lets you add reactors/connections directly into
 * this stage and jump to the solver settings that apply to it.
 *
 * Boulder's solver settings (config.settings.solver) are currently global,
 * not per-stage — so "Solver details" opens the same modal SimulateCard
 * uses, rather than a stage-scoped editor.
 */
export function StageCard({ stageId }: Props) {
  const nodes = useConfigStore((s) => s.config.nodes);
  const config = useConfigStore((s) => s.config);
  const openAddReactor = useAddEntityModalStore((s) => s.openAddReactor);
  const openAddConnection = useAddEntityModalStore((s) => s.openAddConnection);
  const setSolverDetailsOpen = useSolverDetailsStore((s) => s.setOpen);

  const childNodes = useMemo(
    () => nodes.filter((n) => n.group === stageId),
    [nodes, stageId],
  );

  const solver = (config.settings as Record<string, unknown> | null | undefined)?.solver as
    | Record<string, unknown>
    | undefined;
  const kind = (solver?.kind as SolverKind | undefined) ?? "advance_to_steady_state";
  const kindLabel = KIND_LABELS[kind] ?? kind;

  return (
    <div id="stage-card" className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div>
        <h3 className="font-semibold text-sm text-foreground">{stageId}</h3>
        <span className="text-xs text-muted-foreground">Stage</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Button
          id="stage-add-reactor"
          onClick={() => openAddReactor({ group: stageId })}
          variant="muted"
          size="sm"
        >
          + Add Reactor
        </Button>
        <Button
          id="stage-add-connection"
          onClick={() => openAddConnection({ group: stageId })}
          variant="muted"
          size="sm"
        >
          + Add Connection
        </Button>
      </div>

      <div className="border-t border-border pt-2 mt-1">
        <p className="text-xs text-muted-foreground mb-1.5">Child nodes</p>
        <div className="divide-y divide-border">
          {childNodes.map((n) => (
            <div key={n.id} className="py-1 flex items-center justify-between gap-2">
              <span className="text-xs font-mono text-foreground">{n.id}</span>
              <span className="text-xs text-muted-foreground">{n.type}</span>
            </div>
          ))}
          {childNodes.length === 0 && (
            <p className="text-xs text-muted-foreground py-1 italic">No child nodes</p>
          )}
        </div>
      </div>

      <div className="border-t border-border pt-2 mt-1 space-y-1.5">
        <p className="text-xs text-muted-foreground">
          Solves with the mode set in Simulate:{" "}
          <span className="font-mono text-foreground">{kindLabel}</span>. Boulder can't
          mix steady and transient stages in one run.
        </p>
        <Button
          id="stage-solver-details"
          onClick={() => setSolverDetailsOpen(true)}
          variant="secondary"
          size="sm"
        >
          Solver details...
        </Button>
      </div>
    </div>
  );
}
