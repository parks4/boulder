import { getMaxGraphHeight, MIN_GRAPH_HEIGHT } from "@/hooks/useGraphPaneHeight";

interface GraphPaneResizeHandleProps {
  height: number;
  onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void;
}

/**
 * Draggable splitter between the network graph and the results tabs.
 */
export function GraphPaneResizeHandle({ height, onPointerDown }: GraphPaneResizeHandleProps) {
  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label="Resize network graph"
      aria-valuenow={height}
      aria-valuemin={MIN_GRAPH_HEIGHT}
      aria-valuemax={getMaxGraphHeight()}
      data-testid="graph-resize-handle"
      className="group relative z-20 flex h-5 shrink-0 cursor-ns-resize items-center justify-center touch-none select-none py-1"
      onPointerDown={onPointerDown}
    >
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />
      <span className="relative h-1.5 w-14 rounded-full bg-muted-foreground/40 transition-colors group-hover:bg-muted-foreground group-active:bg-primary" />
    </div>
  );
}
