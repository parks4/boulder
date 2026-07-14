import { PanelLeft, PanelRight } from "lucide-react";
import { useLayoutStore } from "@/stores/layoutStore";
import { useShortcutNudge } from "@/hooks/useShortcutNudge";

/** Notify canvas-based components (Cytoscape, Plotly) that the layout changed. */
function nudgeResize() {
  window.dispatchEvent(new Event("resize"));
}

/** Header toggle button in the "collapse sidebar" style. */
export function PaneToggle({ side }: { side: "left" | "right" }) {
  const { leftCollapsed, rightCollapsed, toggleLeft, toggleRight } =
    useLayoutStore();
  const notifyShortcutUsage = useShortcutNudge();
  const collapsed = side === "left" ? leftCollapsed : rightCollapsed;
  const Icon = side === "left" ? PanelLeft : PanelRight;
  const label = `${collapsed ? "Expand" : "Collapse"} ${side} sidebar`;
  return (
    <button
      type="button"
      onClick={() => {
        side === "left" ? toggleLeft() : toggleRight();
        // Only "left" has a keyboard shortcut (Ctrl+B) — see AppShell.
        if (side === "left") notifyShortcutUsage("toggle-left-sidebar", "Ctrl+B");
        // Let the flex layout settle, then re-fit canvases.
        requestAnimationFrame(nudgeResize);
      }}
      title={`${label}${side === "left" ? " (Ctrl+B)" : ""}`}
      aria-label={label}
      aria-pressed={!collapsed}
      className="inline-flex items-center justify-center rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
    >
      <Icon size={18} />
    </button>
  );
}

/** Draggable vertical divider that resizes the adjacent sidebar. */
export function PaneResizer({ side }: { side: "left" | "right" }) {
  const { leftWidth, rightWidth, setLeftWidth, setRightWidth } =
    useLayoutStore();

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = side === "left" ? leftWidth : rightWidth;

    const onMove = (ev: PointerEvent) => {
      const delta = ev.clientX - startX;
      if (side === "left") setLeftWidth(startW + delta);
      else setRightWidth(startW - delta);
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      nudgeResize();
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return (
    <div
      onPointerDown={onPointerDown}
      role="separator"
      aria-orientation="vertical"
      title="Drag to resize"
      className="group relative w-2 shrink-0 self-stretch cursor-col-resize select-none"
    >
      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-border group-hover:bg-blue-500 group-hover:w-0.5 transition-all" />
    </div>
  );
}
