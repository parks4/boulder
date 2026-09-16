/**
 * Which `skip_viz` nodes the graph really hides.
 *
 * Normalisation flags every unfolded composite parent `skip_viz`, but only a
 * parent whose unfolder produced *visible children* should vanish from the
 * graph. Detection heuristic: the node has at least one outgoing mass-flow
 * connection to a node whose id is the parent id plus an underscore (e.g.
 * `cgr → cgr_seg1`).
 *
 * Two kinds of edge must never count as a "child" wiring, whichever way they
 * point:
 * - a `Wall` to a same-group satellite (`pfr → pfr_ambient`, its own heat-loss
 *   sink) — composite children are wired by mass flow, never by a Wall;
 * - the staged solver's stream-point plumbing (`StreamConnector` display edges
 *   and stream-point inlet MFCs). The solver names a reactor's outlet diamond
 *   `<id>_outlet`, so after a run every inter-stage source gains an edge that
 *   matches the prefix rule by coincidence. A design reactor that unfolds into
 *   a satellite (hence `skip_viz`) but stays the reactor itself would then be
 *   drawn during the build and disappear the moment results land, with its
 *   edges rerouted through the outlet diamond.
 *
 * A `skip_viz` node with no such child edge is rendered normally.
 */

type GraphNode = { id: string; metadata?: Record<string, unknown> | null };
type GraphConnection = {
  source: string;
  target: string;
  type?: string | null;
  metadata?: Record<string, unknown> | null;
};

function isChildWiring(c: GraphConnection): boolean {
  if (c.type === "Wall" || c.type === "StreamConnector") return false;
  if (c.metadata?.stream_point) return false;
  return true;
}

export function hiddenCompositeNodeIds(
  nodes: readonly GraphNode[],
  connections: readonly GraphConnection[],
): Set<string> {
  const hidden = new Set<string>();
  for (const node of nodes) {
    if (!node.metadata?.skip_viz) continue;
    const prefix = `${node.id}_`;
    const hasChildConn = connections.some(
      (c) => c.source === node.id && c.target.startsWith(prefix) && isChildWiring(c),
    );
    if (hasChildConn) hidden.add(node.id);
  }
  return hidden;
}
