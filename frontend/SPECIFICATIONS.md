# Boulder Frontend — UI/UX Specifications

This document is the normative reference for Boulder's React + Cytoscape graph
editor behaviour.  Backend API contracts live in the top-level
[SPECIFICATIONS.md](../SPECIFICATIONS.md), [ARCHITECTURE.md](../ARCHITECTURE.md)
and [STONE_SPECIFICATIONS.md](../STONE_SPECIFICATIONS.md).

---

## GRAPH-01 — Layout stability across simulation runs

### Problem

After "Run Simulation" completes, the SSE `complete` event delivers
`updated_nodes` / `updated_connections` (post-build stream-point nodes,
resolved temperatures, etc.).  `setConfig` fires, `buildElements` gets a new
`useCallback` identity, and the `useEffect` that watches it calls
`cy.json({ elements })` + `runGraphLayout`.  The result:

1. All node positions are wiped by `cy.json()`.
2. Dagre re-runs from scratch, re-positioning every node.
3. User-adjusted layout is discarded.
4. A visible flash of the un-aligned layout appears during the animation.

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
   connection-ids, stored in a `useRef`.  `runGraphLayout` is called only when
   the fingerprint changes.
2. **In-place data update** — when the fingerprint is unchanged, iterate over
   nodes and call `cy.getElementById(id).data()` to refresh `temperature` and
   any other visual-data properties.
3. **Selective element merge** — when topology does change, use `cy.add()` /
   `cy.remove()` for only the delta elements rather than `cy.json({ elements
   })`, which wipes all positions.

---

## GRAPH-02 — Persistent manual positions

### Problem

Users may drag nodes to preferred positions.  These are held only in
Cytoscape's canvas state.  Any `cy.json({ elements })` call or `cy.layout()
.run()` discards them.

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
algorithmically computed "natural" position.  This makes stored offsets
topology-independent: if the graph re-lays-out (e.g. after a topology change),
the node tracks its neighbors rather than jumping to a stale absolute coordinate.

1. **Drag-stop** — Cytoscape `dragfree` event captures the node's current
   position, subtracts the natural position stored in `naturalPosRef`, then calls
   `useConfigStore.getState().updateNode(id, { metadata: { ...existing.metadata,
   layout_offset: { dx, dy } } })`.  Topology is unchanged so the data-only config
   effect fires; no layout re-run, node stays where dropped.
2. **Layout pass** — After `nudgeOverlappingNodes`, the current pin-free positions
   are snapshotted into `naturalPosRef`.  Then `applyPinnedPositions(cy)` is
   called: it looks up each node's natural position and adds the stored `layout_offset`.
3. **YAML sync** — because `layout_offset` is in `node.metadata`, it is included
   in `convert_to_stone_format` output and merged back into the YAML tree by
   `merge_config_into_yaml`.  On re-parse it is restored into the config and
   picked up by `applyPinnedPositions` on next layout.
4. **Reset layout** — toolbar button removes `layout_offset` (and legacy
   `layout_pos`) from all node metadata via `setConfig`, clears
   `topoFingerprintRef` to force a full layout pass, then the config effect
   re-runs dagre from scratch.

**Stream-point diamonds** (`{src}_outlet`) are synthesized and not in
`config.nodes`; dragging them is not persisted (acceptable — they auto-place
between stage boxes).

---

## GRAPH-03 — Node shapes by reactor type (P&ID conventions)

| Reactor type | Shape | Rationale |
|---|---|---|
| Tubular / axial-flow reactors (e.g. refractory tubes, wall-profile PFRs) | Wide horizontal rectangle (120 × 48 px) | P&ID tube symbol |
| Well-mixed reactors (PSR, plasma torch, instantaneous mixer) | Ellipse | P&ID stirred vessel |
| `Reservoir` (boundary feed / sink) | Octagon | P&ID source/sink |
| `Reservoir` with `stream_point: true` | Diamond (60 × 60 px) | P&ID material-stream connector |

Plugin authors must add new reactor types to the CSS selector list in
`ReactorGraph.tsx` when they warrant a distinct shape.

---

## GRAPH-04 — Edge styles (P&ID conventions)

| Connection type | Style | Colour |
|---|---|---|
| `MassFlowController`, `Valve` | Solid, width 3 | Gray |
| `StreamConnector` (inter-stage bridge) | Solid, width 2 | Gray |
| `Wall` (energy / heat stream) | Dashed `[8, 4]`, width 1.5 | Orange |

`Wall` edges use a dashed orange line to distinguish energy streams from
material streams at a glance, in line with P&ID conventions.

---

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

---

## GRAPH-06 — Defensive edge rendering

Edges whose source or target node is not rendered (e.g. a placeholder node
marked `skip_viz`) must be **silently skipped**, not cause a Cytoscape crash.
This applies to:

1. Edges from `config.connections` (guarded by `renderedNodeIds`).
2. Synthesised stream-point edges (`${streamId}_to_${conn.target}`) — if
   `conn.target` is not in `renderedNodeIds`, skip the synthesised hop.
3. The upstream `${src}_to_${streamId}` edge — if `src` is not rendered, skip
   both the diamond node and the two-hop edges.

---

## PANEL-01 — Properties panel

| Selected element | Content |
|---|---|
| Regular reactor node | id, type, editable properties |
| Stream-point diamond | Material stream: T, P, ṁ, top species |
| Group compound box | id, "Stage group" label, child-node list (read-only) |
| Edge | Source → Target |
| Nothing selected | Placeholder: "Click a node or edge to view properties." |

---

## PANEL-02 — Convergence tab

| Selected node | Content |
|---|---|
| Spatial reactor (FBS) | FBS heat-loss convergence plot (Φ vs iteration) |
| Residence-time reactor | "Physical residence-time profile is in the Plots tab." |
| PSR (transient) | T, P, X, Y vs time plots |
| Composite group box | "Click on individual segments for convergence." |
| Nothing / no data | "Select a reactor node to view convergence data." |

---

## PANEL-03 — Node colour coding

Node background colour is mapped from `temperature` data:
- Cold (300 K) → `deepskyblue`
- Hot (2273 K) → `tomato`

Temperature is updated in-place (see GRAPH-01) without triggering a layout
pass.
