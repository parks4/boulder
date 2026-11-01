import { toast } from "sonner";
import { useScenarioStore } from "@/stores/scenarioStore";

/** Query parameter selecting a scenario once the preloaded config has loaded. */
export const SCENARIO_DEEP_LINK_PARAM = "scenario";

/**
 * Honour a ``/?scenario=<id>`` deep link: select that scenario in this tab only.
 *
 * Call once the preloaded config is in place. The parameter is removed from the
 * URL first, so a reload never re-applies it. The scenario list is re-seeded
 * from the newly loaded config before the lookup; an unknown id yields a
 * non-blocking toast and leaves the selection untouched.
 */
export async function applyScenarioDeepLink(): Promise<void> {
  const url = new URL(window.location.href);
  // `get` URL-decodes, so ids containing "/" or "=" round-trip.
  const id = url.searchParams.get(SCENARIO_DEEP_LINK_PARAM);
  if (id === null) return;
  url.searchParams.delete(SCENARIO_DEEP_LINK_PARAM);
  window.history.replaceState(window.history.state, "", url);

  await useScenarioStore.getState().resetForNewConfig();
  const { authoredIds, scenarios, setActive } = useScenarioStore.getState();
  if (authoredIds.includes(id) || scenarios.some((s) => s.id === id)) {
    await setActive(id);
  } else {
    toast.error(`Scenario "${id}" not found in the loaded configuration.`);
  }
}
