import { useEffect } from "react";
import { SCENARIO_FOCUS_STREAM_URL } from "@/api/scenarios";
import { useScenarioStore } from "@/stores/scenarioStore";

/**
 * Subscribe to the backend scenario-focus stream so an external tool (e.g. a
 * standalone result dashboard) can drive this GUI to load a scenario live.
 *
 * On each ``focus`` event it calls the existing ``setActive`` sink — the same
 * path the Scenario Pane uses — so the trajectory appears in the Plots tab with
 * no page reload. Harmless when no scenario store is configured (the id simply
 * won't resolve).
 */
export function useScenarioFocus() {
  useEffect(() => {
    const source = new EventSource(SCENARIO_FOCUS_STREAM_URL);

    source.addEventListener("focus", (e: MessageEvent) => {
      try {
        const { scenario_id } = JSON.parse(e.data) as { scenario_id: string };
        if (scenario_id) {
          void useScenarioStore.getState().setActive(scenario_id);
        }
      } catch {
        /* ignore malformed events */
      }
    });

    source.onerror = () => {
      // Transient disconnect — EventSource auto-reconnects.
    };

    return () => source.close();
  }, []);
}
