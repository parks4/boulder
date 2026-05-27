import { useCallback, useState, type PointerEvent as ReactPointerEvent } from "react";

export const DEFAULT_GRAPH_HEIGHT = 360;
export const MIN_GRAPH_HEIGHT = 200;
const GRAPH_HEIGHT_STORAGE_KEY = "boulder-graph-height";

/** Leave room for header, sidebar chrome, and at least a sliver of results tabs. */
const VIEWPORT_BOTTOM_MARGIN = 160;

export function getMaxGraphHeight(): number {
  if (typeof window === "undefined") return 1200;
  return Math.max(
    MIN_GRAPH_HEIGHT,
    Math.floor(window.innerHeight - VIEWPORT_BOTTOM_MARGIN),
  );
}

export function loadStoredGraphHeight(): number {
  if (typeof window === "undefined") return DEFAULT_GRAPH_HEIGHT;
  const raw = localStorage.getItem(GRAPH_HEIGHT_STORAGE_KEY);
  if (!raw) return DEFAULT_GRAPH_HEIGHT;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return DEFAULT_GRAPH_HEIGHT;
  return Math.min(getMaxGraphHeight(), Math.max(MIN_GRAPH_HEIGHT, parsed));
}

function saveGraphHeight(height: number): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(GRAPH_HEIGHT_STORAGE_KEY, String(height));
}

function clampGraphHeight(height: number): number {
  return Math.min(getMaxGraphHeight(), Math.max(MIN_GRAPH_HEIGHT, height));
}

export function useGraphPaneHeight() {
  const [graphPaneHeight, setGraphPaneHeight] = useState(loadStoredGraphHeight);

  const onResizePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();

      const handle = event.currentTarget;
      handle.setPointerCapture(event.pointerId);

      const startY = event.clientY;
      const startHeight = graphPaneHeight;

      const handlePointerMove = (moveEvent: PointerEvent) => {
        if (moveEvent.pointerId !== event.pointerId) return;
        const delta = moveEvent.clientY - startY;
        setGraphPaneHeight(clampGraphHeight(startHeight + delta));
      };

      const endResize = (endEvent: PointerEvent) => {
        if (endEvent.pointerId !== event.pointerId) return;
        const delta = endEvent.clientY - startY;
        const finalHeight = clampGraphHeight(startHeight + delta);
        saveGraphHeight(finalHeight);
        setGraphPaneHeight(finalHeight);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        handle.releasePointerCapture(event.pointerId);
        handle.removeEventListener("pointermove", handlePointerMove);
        handle.removeEventListener("pointerup", endResize);
        handle.removeEventListener("pointercancel", endResize);
      };

      document.body.style.cursor = "ns-resize";
      document.body.style.userSelect = "none";
      handle.addEventListener("pointermove", handlePointerMove);
      handle.addEventListener("pointerup", endResize);
      handle.addEventListener("pointercancel", endResize);
    },
    [graphPaneHeight],
  );

  return { graphPaneHeight, onResizePointerDown };
}
