import { useEffect, useState } from "react";
import { fetchSpeciesColors } from "@/api/uiConfig";

let cache: Record<string, string> | null = null;
let inflight: Promise<Record<string, string>> | null = null;

/**
 * Species -> hex color palette a host plugin has registered (the same one
 * the Sankey diagram uses for its species bands), so composition plots can
 * render a given species with the same color. Empty when no plugin
 * registers one. Fetched once per session and cached.
 */
export function useSpeciesColors(): Record<string, string> {
  const [state, setState] = useState<Record<string, string>>(cache ?? {});

  useEffect(() => {
    if (cache) return;
    if (!inflight) inflight = fetchSpeciesColors();
    let cancelled = false;
    inflight
      .then((colors) => {
        cache = colors;
        if (!cancelled) setState(colors);
      })
      .catch(() => {
        // Best-effort; callers fall back to their own default colorway.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
