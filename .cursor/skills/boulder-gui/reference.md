# Boulder GUI — API & automation reference

Base URL assumed: `http://127.0.0.1:8050`.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/configs/preloaded` | Config loaded at server start (`preloaded`, `config`, `yaml`, `filename`) |
| GET | `/api/configs/default` | Built-in empty template |
| POST | `/api/configs/upload` | Multipart YAML/YML/PY upload |
| POST | `/api/configs/validate` | Validate normalized config JSON |
| POST | `/api/simulations` | Body: `{"config": {...}}` → `{simulation_id}` |
| GET | `/api/simulations/{id}/stream` | SSE progress (`complete`, `error`, partial updates) |
| GET | `/api/simulations/{id}/results` | Full results when done; `status: running` while active |

## SSE stream (browser-equivalent completion)

```python
import urllib.request, json

sim_id = "..."  # from POST /api/simulations
with urllib.request.urlopen(
        f"http://127.0.0.1:8050/api/simulations/{sim_id}/stream") as r:
    event = None
    while True:
        line = r.readline().decode().strip()
        if not line:
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:") and event in ("complete", "error"):
            payload = json.loads(line[5:])
            print(event, payload.get("error_message"))
            break
```

On `complete`, payload includes `reactor_reports`, `updated_nodes`, `updated_connections`, `sankey_*`, `summary`, `elapsed_time`.

## Results shape (thermo checks)

```python
reports = payload["reactor_reports"]  # dict[node_id → report]
report = reports["outlet"]
report["T"]       # K
report["P"]       # Pa
report["X"]       # mole fractions dict
report["reactor_report"]   # human-readable multi-line str
report["thermo_report"]    # Cantera phase report str
```

Reservoir / OutletSink entries use the reservoir branch of `_generate_reactor_reports` (fixed-state wording in `reactor_report` even when T reflects solved outlet).

## Preloaded vs client config

The UI sends the **in-memory normalized config** from Zustand (`useConfigStore`) to `POST /api/simulations`, not a re-read of disk. After server restart, the browser reload pulls fresh preload via `GET /api/configs/preloaded` on mount (`AppShell.tsx`).

If the header filename is wrong, the client may still hold an old config — reload the page.

## Browser MCP tool sequence

```
browser_navigate → http://127.0.0.1:8050/
browser_snapshot (take_screenshot_afterwards: true)
browser_click → Run Simulation button ref
# wait until "Download Python" appears in snapshot
browser_click → Thermo tab
browser_snapshot (take_screenshot_afterwards: true)
browser_mouse_click_xy → screenshot coords on target node (target: canvas)
browser_snapshot → read Thermo panel text in screenshot / search if rendered
```

Unlock browser when finished: `browser_lock` action `unlock`.

## Plugins

Custom reactor kinds register via `boulder.plugins` entry points or the `BOULDER_PLUGINS` environment variable (dotted module path). The CLI may also pass `--runner PKG.MOD:CLASS` for a custom load/normalize pipeline.

Symptom: `Unsupported reactor type: 'MyKind'` → plugin package not loaded or builder not registered.

## Frontend rebuild

```bash
conda activate boulder
cd frontend && npm run build
```

Restart uvicorn after backend or static asset changes.
