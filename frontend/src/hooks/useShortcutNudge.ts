import { useCallback, useRef } from "react";
import { toast } from "sonner";

/** A click is only counted toward a nudge if it lands within this window. */
export const NUDGE_WINDOW_MS = 60_000;
/** Clicks needed within the window before nudging (never on the first click or two). */
export const NUDGE_THRESHOLD = 3;

/**
 * Returns `notify(actionId, shortcutLabel)` — call it from a button's
 * onClick (never from the shortcut's own keydown handler, since using the
 * shortcut is the desired behavior, not something to correct). After
 * `NUDGE_THRESHOLD` clicks on the same `actionId` within `NUDGE_WINDOW_MS`,
 * shows a toast naming the keyboard shortcut instead, then resets so the
 * next nudge needs a fresh run of clicks rather than firing on every click.
 */
export function useShortcutNudge() {
  const clicksByAction = useRef(new Map<string, number[]>());

  return useCallback((actionId: string, shortcutLabel: string) => {
    const now = Date.now();
    const recent = (clicksByAction.current.get(actionId) ?? []).filter(
      (t) => now - t < NUDGE_WINDOW_MS,
    );
    recent.push(now);
    if (recent.length >= NUDGE_THRESHOLD) {
      toast.info(`Tip: press ${shortcutLabel} instead of clicking`);
      clicksByAction.current.set(actionId, []);
    } else {
      clicksByAction.current.set(actionId, recent);
    }
  }, []);
}
