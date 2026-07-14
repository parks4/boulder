import { useEffect, useState } from "react";
import { fetchKinds, type KindInfo } from "@/api/kinds";

interface KindsState {
  reactors: KindInfo[];
  connections: KindInfo[];
}

let cache: KindsState | null = null;
let inflight: Promise<KindsState> | null = null;

/**
 * Reactor/connection kinds this Boulder build can construct, with a Cantera
 * doc link where one exists. Fetched once per session and cached — the type
 * registry doesn't change while the server is running.
 */
export function useKinds(): KindsState {
  const [state, setState] = useState<KindsState>(
    cache ?? { reactors: [], connections: [] },
  );

  useEffect(() => {
    if (cache) return;
    if (!inflight) inflight = fetchKinds();
    let cancelled = false;
    inflight
      .then((kinds) => {
        cache = kinds;
        if (!cancelled) setState(kinds);
      })
      .catch(() => {
        // Type registry is best-effort; callers fall back to their own defaults.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
