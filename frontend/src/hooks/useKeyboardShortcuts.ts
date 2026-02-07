import { useEffect } from "react";

/**
 * Global keyboard shortcut handler.
 *
 * - Ctrl+Enter: triggers the provided `onRunSimulation` callback.
 */
export function useKeyboardShortcuts(onRunSimulation: () => void) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        onRunSimulation();
      }
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onRunSimulation]);
}
