import type { SimulationResults } from "@/types/simulation";

type SankeyResults = SimulationResults & {
  sankey_links: NonNullable<SimulationResults["sankey_links"]>;
  sankey_nodes: NonNullable<SimulationResults["sankey_nodes"]>;
};

/** True when the backend produced Sankey link/node payload for rendering. */
export function hasSankeyData(
  results: Pick<SimulationResults, "sankey_links" | "sankey_nodes">,
): results is SankeyResults {
  return results.sankey_links != null && results.sankey_nodes != null;
}
