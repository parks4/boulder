import type { SimulationResults } from "@/types/simulation";

/** True when the backend produced Sankey link/node payload for rendering. */
export function hasSankeyData(
  results: Pick<SimulationResults, "sankey_links" | "sankey_nodes">,
): boolean {
  return results.sankey_links != null && results.sankey_nodes != null;
}
