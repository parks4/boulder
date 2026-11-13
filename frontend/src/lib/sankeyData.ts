import type { SimulationResults } from "@/types/simulation";

type SankeyResults = SimulationResults & {
  sankey_links: NonNullable<SimulationResults["sankey_links"]>;
  sankey_nodes: NonNullable<SimulationResults["sankey_nodes"]>;
};

/**
 * Above this many links the Sankey tab draws nothing: Plotly blocks the page
 * for seconds (12 s at 6000 links) and the diagram is unreadable anyway.
 */
export const SANKEY_MAX_LINKS = 2000;

/** True when the backend produced Sankey link/node payload for rendering. */
export function hasSankeyData(
  results: Pick<SimulationResults, "sankey_links" | "sankey_nodes">,
): results is SankeyResults {
  return results.sankey_links != null && results.sankey_nodes != null;
}
