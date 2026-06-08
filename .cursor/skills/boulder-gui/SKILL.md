______________________________________________________________________

## name: boulder-gui description: >- Start, drive, and verify the Boulder web GUI (FastAPI + React/Cytoscape) for STONE YAML simulations. Use when the user asks to run a simulation in the browser, test the UI, click nodes, read Thermo/Summary tabs, preload a YAML, or automate E2E checks against localhost:8050. Covers server startup, config loading, graph interaction, results tabs, and API fallbacks when browser canvas clicks fail.

# Boulder GUI

Guide for agents verifying STONE simulations through the web UI or its HTTP API.

## When to use what

| Goal | Prefer |
|------|--------|
| Assert outlet T, stream points, staged solve | **HTTP API** (reproducible, no canvas coords) |
| Visual layout, UX, tab wiring | **Browser MCP** |
| Custom reactor kinds via plugins | `BOULDER_PLUGINS` + registered plugin package |

Always rebuild frontend after UI changes: `cd frontend && npm run build`.

## Start the server

Default URL: `http://127.0.0.1:8050`. Health: `GET /api/health`.

```bash
conda activate boulder
cd frontend && npm run build && cd ..
boulder path/to/config.yaml --no-open
# or: boulder --no-open   # empty / default config
```

Optional plugins (entry points or `BOULDER_PLUGINS` env var) load at startup.

After changing the YAML on disk, **restart the server** — preloaded config is read once at startup.

## UI layout

```
┌─────────────────────────────────────────────────────────────┐
│ Header: [filename.yaml]  Light/Dark                         │
├──────────────┬──────────────────────────────────────────────┤
│ Edit Network │         Reactor graph (Cytoscape canvas)       │
│ Simulate     │         Click nodes/edges to select            │
│ Properties   │                                              │
├──────────────┴──────────────────────────────────────────────┤
│ Results: Plots | Sankey | Thermo | Summary | Convergence    │
│          (+ plugin tabs e.g. Network)                         │
└─────────────────────────────────────────────────────────────┘
```

- **Header filename button** — opens YAML editor (Save/Cancel).
- **Upload Config** — load `.yaml` / `.yml` / `.py` from disk.
- **Run Simulation (Ctrl+Enter)** — disabled when config has no nodes or a run is in progress.
- **Properties panel** (left) — selected node/edge fields; stream points and terminal sinks show computed Material Stream (read-only after solve).
- **Graph** — nodes are circles (reactors) or octagons (reservoirs/sinks); edges are flow devices.

## Standard agent workflow (browser)

Copy and track:

```
GUI check:
- [ ] Server up (/api/health)
- [ ] Preloaded config matches expected YAML (/api/configs/preloaded)
- [ ] Page shows correct filename (not untitled.yaml)
- [ ] Run Simulation → completes (Download Python button appears)
- [ ] Select target node → Thermo tab shows expected T/P/composition
```

1. Navigate to `http://127.0.0.1:8050/` (hard refresh if assets 404 or MIME errors after a frontend rebuild).
1. Confirm header shows the expected `*.yaml` name. If it shows `untitled.yaml`, wait for preload toast or reload; click filename to verify YAML content.
1. Click **Run Simulation** (or wait until enabled).
1. Wait for **Download Python** and result tabs — not "Running...".
1. Open **Thermo** tab.
1. **Select a node** on the graph (see canvas clicks below).
1. Read `reactor_report` / thermo text in the tab; cross-check via API if critical.

### Graph selection (browser automation)

- The graph is a **Cytoscape `<canvas>`** — node ids are **not** exposed to `browser_search`.
- **Single click** on a node → selects it (Properties + Thermo).
- **Double click** on a node within ~300 ms → also switches to **Thermo** tab.
- **Single click** on a **MassFlowController** edge → selects it and opens **Thermo** (shows source reactor T/P/X and mdot).

**Reliable click pattern (cursor-ide-browser):**

1. `browser_snapshot` with `take_screenshot_afterwards: true`.
1. Immediately `browser_mouse_click_xy` using **screenshot coordinates** on the node center.
1. Target must be `<canvas>`, not `#graph-container` or the sidebar grid.
1. If click fails, take a **fresh** screenshot before retrying (cache invalidates).

Clicks are fragile at narrow viewports — resize browser wider if needed. When automation cannot select a node, use the **API verification** below; do not loop on coordinates.

## Results tabs

| Tab | Needs selection? | Content |
|-----|------------------|---------|
| **Plots** | No | Time series after transient runs |
| **Sankey** | No | Species / energy flows (plugin may customize) |
| **Thermo** | **Yes** — node or MFC | `reactor_report`, full Cantera `thermo_report` |
| **Summary** | No | Elapsed time, text summary |
| **Convergence** | No | Staged-solve progress (redirects residence profiles to Plots when applicable) |
| **Network** | Plugin | Live reactor network view |

Terminal **OutletSink** nodes: post-solve thermo comes from `_refresh_terminal_sinks` (legacy path). **Inter-stage stream-point** diamonds (`{source}_outlet`) are refreshed during staged solve — preferred for multi-stage models.

## API verification (preferred for agents)

Same server session as the browser. See [reference.md](reference.md) for full scripts.

Quick checks:

```python
import json, urllib.request

base = "http://127.0.0.1:8050"
pre = json.loads(urllib.request.urlopen(f"{base}/api/configs/preloaded").read())
assert pre["preloaded"]
```

Start simulation → poll results:

```python
import time
req = urllib.request.Request(
    f"{base}/api/simulations",
    data=json.dumps({"config": pre["config"]}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
sim_id = json.loads(urllib.request.urlopen(req).read())["simulation_id"]
for _ in range(120):
    st = json.loads(urllib.request.urlopen(
        f"{base}/api/simulations/{sim_id}/results").read())
    if st.get("is_complete") or st.get("status") == "error":
        break
    time.sleep(0.5)

reports = st["reactor_reports"]
T_K = reports["outlet"]["T"]
assert T_K > 300, f"outlet stuck at placeholder T: {T_K} K"
```

Assert invariants on `updated_nodes` / `updated_connections` when testing staged networks (stream points present, no duplicate interface edges).

## Common failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `untitled.yaml`, Run disabled | No preload; empty default | Start with YAML arg or Upload Config |
| Outlet 25 °C / N2 | Terminal `Reservoir` placeholder, or stale preload | Use `OutletSink: {}`; restart server |
| `Unsupported reactor type` | Kind not in core Boulder; plugin not loaded | Set `BOULDER_PLUGINS`; restart server |
| JS chunk MIME `text/html` | Stale frontend hash or SPA catch-all | `npm run build`, restart server, hard refresh |
| Thermo says "Select a node…" | Nothing selected, or canvas click missed | Retry canvas click or use API |
| Properties Material Stream empty | `terminal_sink` not in `updated_nodes` yet | Thermo tab / API `reactor_reports` still authoritative |

## Dev mode (human)

`boulder --dev` — Vite on `:5173` proxies `/api` to backend. Agents testing production-like behavior should use built `frontend/dist` (default server).

## Further reading

- [reference.md](reference.md) — SSE stream, upload endpoint, browser checklist
- Repo [AGENTS.md](../../../AGENTS.md) — conda env, `make qa`, targeted tests
