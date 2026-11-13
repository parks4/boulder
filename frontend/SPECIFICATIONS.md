# Boulder Frontend — UI/UX Specifications

This document is the normative reference for Boulder's React + Cytoscape graph
editor behaviour. Backend API contracts live in the top-level
[SPECIFICATIONS.md](../SPECIFICATIONS.md), [ARCHITECTURE.md](../ARCHITECTURE.md)
and [STONE_SPECIFICATIONS.md](../STONE_SPECIFICATIONS.md).

______________________________________________________________________

## GRAPH-01 — Layout stability across simulation runs

### Problem

After "Run Simulation" completes, the SSE `complete` event delivers
`updated_nodes` / `updated_connections` (post-build stream-point nodes,
resolved temperatures, etc.). `setConfig` fires, `buildElements` gets a new
`useCallback` identity, and the `useEffect` that watches it calls
`cy.json({ elements })` + `runGraphLayout`. The result:

1. All node positions are wiped by `cy.json()`.
1. Dagre re-runs from scratch, re-positioning every node.
1. User-adjusted layout is discarded.
1. A visible flash of the un-aligned layout appears during the animation.

### Required behaviour

- **The graph topology must not change during or after simulation unless new
  nodes or connections are actually added or removed.**
- When only node *properties* change (temperature, composition) update node
  data in-place (`cy.getElementById(id).data({...})`) without triggering a
  layout pass.
- When the topology *does* change (new nodes/connections appear after build),
  only newly-added elements should be positioned; existing node positions must
  be preserved.

### Implementation

1. **Topology fingerprint** — a stable string built from sorted node-ids +
   connection-ids, stored in a `useRef`. `runGraphLayout` is called only when
   the fingerprint changes.
1. **In-place data update** — when the fingerprint is unchanged, iterate over
   nodes and call `cy.getElementById(id).data()` to refresh `temperature` and
   any other visual-data properties.
1. **Selective element merge** — when topology does change, use `cy.add()` /
   `cy.remove()` for only the delta elements rather than `cy.json({ elements })`, which wipes all positions.

______________________________________________________________________

## GRAPH-02 — Persistent manual positions

### Problem

Users may drag nodes to preferred positions. These are held only in
Cytoscape's canvas state. Any `cy.json({ elements })` call or `cy.layout() .run()` discards them.

### Required behaviour

- Manually dragged node positions must survive:
  - Simulation runs (see GRAPH-01).
  - Theme changes.
  - Panel resize events.
  - Inline YAML save and re-parse.
- A **Reset layout** button must be available to discard all pinned positions
  and re-run the full dagre + `alignLayoutLanes` pass.

### Implementation

Single source of truth: `metadata.layout_offset: {dx, dy}` on the node, stored
as part of the config and round-tripped through the YAML sync pipeline.
`dx` and `dy` are the manual drag offset in pixels relative to the node's
algorithmically computed "natural" position. This makes stored offsets
topology-independent: if the graph re-lays-out (e.g. after a topology change),
the node tracks its neighbors rather than jumping to a stale absolute coordinate.

1. **Drag-stop** — Cytoscape `dragfree` event captures the node's current
   position, subtracts the natural position stored in `naturalPosRef`, then calls
   `useConfigStore.getState().updateNode(id, { metadata: { ...existing.metadata, layout_offset: { dx, dy } } })`. Topology is unchanged so the data-only config
   effect fires; no layout re-run, node stays where dropped.
1. **Layout pass** — After `nudgeOverlappingNodes`, the current pin-free positions
   are snapshotted into `naturalPosRef`. Then `applyPinnedPositions(cy)` is
   called: it looks up each node's natural position and adds the stored `layout_offset`.
1. **YAML sync** — because `layout_offset` is in `node.metadata`, it is included
   in `convert_to_stone_format` output and merged back into the YAML tree by
   `merge_config_into_yaml`. On re-parse it is restored into the config and
   picked up by `applyPinnedPositions` on next layout.
1. **Reset layout** — toolbar button removes `layout_offset` (and legacy
   `layout_pos`) from all node metadata via `setConfig`, clears
   `topoFingerprintRef` to force a full layout pass, then the config effect
   re-runs dagre from scratch.

**Stream-point diamonds** (`{src}_outlet`) are synthesized and not in
`config.nodes`; dragging them is not persisted (acceptable — they auto-place
between stage boxes).

______________________________________________________________________

## GRAPH-03 — Node shapes by reactor type (P&ID conventions)

| Reactor type | Shape | Rationale |
|---|---|---|
| Tubular / axial-flow reactors (e.g. refractory tubes, wall-profile PFRs) | Wide horizontal rectangle (120 × 48 px) | P&ID tube symbol |
| Well-mixed reactors (PSR, plasma torch, instantaneous mixer) | Ellipse | P&ID stirred vessel |
| `Reservoir` (boundary feed / sink) | Octagon | P&ID source/sink |
| `Reservoir` with `stream_point: true` | Diamond (60 × 60 px) | P&ID material-stream connector |

Plugin authors must add new reactor types to the CSS selector list in
`ReactorGraph.tsx` when they warrant a distinct shape.

______________________________________________________________________

## GRAPH-04 — Edge styles (P&ID conventions)

| Connection type | Style | Colour |
|---|---|---|
| `MassFlowController`, `Valve` | Solid, width 3 | Gray |
| `StreamConnector` (inter-stage bridge) | Solid, width 2 | Gray |
| `Wall` (energy / heat stream) | Dashed `[8, 4]`, width 1.5 | Orange |

`Wall` edges use a dashed orange line to distinguish energy streams from
material streams at a glance, in line with P&ID conventions.

______________________________________________________________________

## GRAPH-05 — Composite reactor group interaction

### Required behaviour

- Clicking a compound group box selects the **group**, not a child.
- The left panel shows the group id, label "Stage group", and a read-only list
  of child nodes.
- The **Plots** tab shows the group-level aggregated spatial profile when one
  has been registered under the stage id in `reactors_series`.
- The **Convergence** tab shows:
  *"Click on individual segments for convergence."*
- Clicking a child node within the group selects the child normally.

### Composite layout metadata

Unfolders may attach the following keys to child node `metadata` to guide layout:

| Key | Type | Effect |
|---|---|---|
| `layout_lane: "main_flow"` | string | Primary flow axis; topological sort determines X. |
| `layout_y_offset` | number (px) | Y from `mainFlowY`; negative = above. |
| `layout_x_offset` | number (px) | X shift from anchor node. |
| `layout_anchor` | string (node id) | Explicit main-flow node for X anchor (overrides connection heuristic). |
| `skip_viz: true` | boolean | Node is a hidden placeholder; skip rendering and all layout. |
| `layout_offset: {dx, dy}` | `{dx: number, dy: number}` | Manual drag offset (px) from the node's computed layout position. Survives re-layout by tracking neighbors. Set by drag-stop, cleared by Reset layout. |
| `layout_position: {x, y}` | `{x: number, y: number}` | Absolute canvas position, see GRAPH-07. Never cleared by Reset layout. |

______________________________________________________________________

## GRAPH-06 — Defensive edge rendering

Edges whose source or target node is not rendered (e.g. a placeholder node
marked `skip_viz`) must be **silently skipped**, not cause a Cytoscape crash.
This applies to:

1. Edges from `config.connections` (guarded by `renderedNodeIds`).
1. Synthesised stream-point edges (`${streamId}_to_${conn.target}`) — if
   `conn.target` is not in `renderedNodeIds`, skip the synthesised hop.
1. The upstream `${src}_to_${streamId}` edge — if `src` is not rendered, skip
   both the diamond node and the two-hop edges.

______________________________________________________________________

## GRAPH-07 — Large networks and absolute positions

Networks generated by a tool (e.g. a compartment network built from a flow field) can have
thousands of nodes and connections, with recirculation loops and exchange pairs of opposite
`MassFlowController`s. Their nodes usually have a physical position.

### Absolute positions — `metadata.layout_position`

```yaml
- id: cell_12
  IdealGasConstPressureMoleReactor: {...}
  metadata:
    layout_position: {x: 480, y: 160}
```

`x`, `y` are Cytoscape model coordinates (canvas units, `y` pointing down, the unit of
`layout_offset` at zoom 1). Both must be finite numbers, otherwise the key is ignored.

- **Every drawn node carries it** (composite placeholders and stream-point diamonds aside): the
  graph is drawn at those positions with a `preset` layout; no dagre pass, no lane alignment, no
  overlap nudge. Stream-point diamonds are centred on the nodes they connect.
- **Some nodes carry it**: today's dagre + lane layout runs, then the nodes that carry it are moved
  to their position.
- `layout_offset` (drag) applies on top, as for any node; Reset layout keeps `layout_position`.

### Cycles

Lane inference (no `layout_lane` anywhere) must terminate on cyclic networks: the longest-path pass
that picks the main-flow spine only follows edges forward in its topological order (cycle members
are appended in declaration order), so the spine trace-back cannot loop.

### Cheap style above `LARGE_GRAPH_ELEMENTS`

When nodes + connections exceed `LARGE_GRAPH_ELEMENTS` (1000, `lib/graphLayout.ts`), edges are
drawn straight, 1 px wide, with small arrows and no label, and node labels are hidden below a
10 px rendered font size. `minZoom` is 0.02 so that such a network fits the pane.

Above the threshold, nodes without `layout_position` are placed by Cytoscape's `breadthfirst`
layout, without lane alignment: dagre takes seconds at 100 nodes and freezes the page at a thousand.
Generated networks should carry positions.

The Sankey tab draws nothing above `SANKEY_MAX_LINKS` (2000, `lib/sankeyData.ts`) links and says
so: Plotly blocks the page for about 12 s on 6000 links, and such a diagram is unreadable.

______________________________________________________________________

## PANEL-01 — Properties panel

| Selected element | Content |
|---|---|
| Regular reactor node | id, type, editable properties |
| Stream-point diamond | Material stream: T, P, ṁ, top species |
| Group compound box | id, "Stage group" label, child-node list (read-only) |
| Edge | Source → Target |
| Nothing selected | Placeholder: "Click a node or edge to view properties." |

______________________________________________________________________

## PANEL-02 — Convergence tab

| Selected node | Content |
|---|---|
| Spatial reactor (FBS) | FBS heat-loss convergence plot (Φ vs iteration) |
| Residence-time reactor | "Physical residence-time profile is in the Plots tab." |
| PSR (transient) | T, P, X, Y vs time plots |
| Composite group box | "Click on individual segments for convergence." |
| Nothing / no data | "Select a reactor node to view convergence data." |

______________________________________________________________________

## PANEL-03 — Node colour coding

Once a solve has results, each node whose reactor report carries a temperature (`reactor_reports[id].T`)
is filled by that temperature, linearly over the solved range `[Tmin, Tmax]` of the drawn nodes:

- `Tmin` → `deepskyblue` (`#4A90E2` in dark theme)
- `Tmax` → `tomato` (`#E94B3C` in dark theme)

A legend (bottom left) shows the gradient and `Tmin`/`Tmax` in K. Nodes flagged with a warning badge
keep their fill under the badge. Before any result the nodes keep the default grey. The Sankey keeps
its fixed 300–2273 K scale (`lib/cytoscapeNodeColor.ts`).

The fill is updated in-place (see GRAPH-01) without triggering a layout
pass.
