"""FastAPI application entry point for Boulder.

This module creates the FastAPI app, configures CORS middleware,
registers all API routes, and serves the React frontend in production.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

# Load .env from the repository root (one level above the package directory)
# so that BOULDER_PLUGINS and other settings can be configured per-project
# without modifying this file.  python-dotenv is an optional dependency;
# a missing file or missing package is silently ignored.
try:
    from dotenv import load_dotenv  # type: ignore

    _env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_file.is_file():
        load_dotenv(dotenv_path=_env_file, override=False)
        logging.getLogger(__name__).debug(f"Loaded .env from {_env_file}")
except ImportError:
    pass  # python-dotenv not installed; rely on system environment

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import (
    configs,
    graph,
    gui_actions,
    mechanisms,
    plugins,
    scenarios,
    simulations,
    sweep,
    ui,
)

logger = logging.getLogger(__name__)


_converter_class = None  # overridable by CLI before uvicorn starts
_runner_class = None  # overridable by CLI before uvicorn starts


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    from ..verbose_utils import ensure_boulder_console_logging

    ensure_boulder_console_logging()

    # Startup: register built-in plugins and create global converter
    from ..cantera_converter import DualCanteraConverter
    from ..network_plugin import register_network_plugin

    register_network_plugin()
    converter_cls = _converter_class or DualCanteraConverter
    # Store converter class so simulation routes can instantiate their own.
    app.state.converter_class = converter_cls
    # Store runner class so routes can use its normalize/validate pipeline.
    from ..runner import BoulderRunner as _BoulderRunner

    app.state.runner_class = _runner_class or _BoulderRunner
    # Store a shared converter on the app state for routes to access
    # Handle potential Unicode issues on Windows by creating with a safe default
    try:
        app.state.converter = converter_cls()
    except (UnicodeEncodeError, ValueError) as e:
        logger.warning(f"Failed to initialize converter with plugins: {e}")
        logger.warning("Starting with minimal plugin support")
        # Create a basic converter without problematic plugins
        app.state.converter = converter_cls()

    # Load initial configuration from environment variable if provided
    env_config_path = os.environ.get("BOULDER_CONFIG_PATH") or os.environ.get(
        "BOULDER_CONFIG"
    )
    app.state.preloaded_config = None
    app.state.preloaded_yaml = None
    app.state.preloaded_filename = None
    app.state.preloaded_config_path = None  # full path for script generation
    app.state.preloaded_result = None
    app.state.preloaded_fingerprint = None
    app.state.scenario_store_path = None
    app.state.preloaded_raw = None  # inheritance-resolved config (keeps sweeps:)
    app.state.sweep_job = None
    # ``--sweep`` GUI mode (BOULDER_SWEEP_MODE): default the split button to Run Sweep.
    app.state.sweep_default = bool(os.environ.get("BOULDER_SWEEP_MODE"))
    # ``--run`` autorun is decided later, once the cache / scenario store is known.
    app.state.autorun = False
    # Theme the GUI publishes (POST /api/ui/theme) for external tools to mirror.
    app.state.ui_theme = None

    if env_config_path and env_config_path.strip():
        try:
            from ..runner import BoulderRunner

            cleaned = env_config_path.strip()
            verbose = os.environ.get("BOULDER_VERBOSE") == "1"

            if verbose:
                logger.info(f"Loading preloaded configuration from: {cleaned}")

            # Use the runner class registered by the CLI (e.g. a host-package
            # subclass) so that its load() override is respected.  A custom
            # runner may resolve YAML ``from:`` inheritance before Boulder's
            # normaliser sees the config.  Fall back to the standard loader for
            # plain Boulder use.
            runner_cls = _runner_class or BoulderRunner
            config = runner_cls.load(cleaned)
            # Keep the inheritance-resolved config before normalize strips
            # ``sweeps:`` — the Run Sweep button needs to see it.
            app.state.preloaded_raw = config

            # Keep the original YAML string for the editor panel.  For inheritance
            # overlays the "original" shown is the leaf file (what the user opened),
            # not the fully-merged result.
            with open(cleaned, "r", encoding="utf-8") as _f:
                original_yaml = _f.read()
            actual_yaml_path = cleaned

            normalized = runner_cls.normalize(config)
            validated = runner_cls.validate(normalized)

            app.state.preloaded_config = validated
            app.state.preloaded_yaml = original_yaml
            app.state.preloaded_filename = os.path.basename(actual_yaml_path)
            app.state.preloaded_config_path = str(actual_yaml_path)

            logger.info(f"Preloaded configuration: {app.state.preloaded_filename}")

            # Attempt to load a matching cache entry for the preloaded config.
            try:
                from ..result_cache import (
                    cache_dir_for,
                    lookup_cached_result,
                    resolve_mechanism_for_fingerprint,
                )

                cache_root = cache_dir_for(str(actual_yaml_path))
                if os.environ.get("BOULDER_NO_CACHE"):
                    # --no-cache: don't pick up any cached result; recompute.
                    app.state.preloaded_result = None
                    app.state.preloaded_fingerprint = None
                    print("[cache] disabled (--no-cache) — will recompute", flush=True)
                elif cache_root is not None:
                    mechanism = resolve_mechanism_for_fingerprint(
                        validated, converter_class=app.state.converter_class
                    )
                    fingerprint, cached = lookup_cached_result(
                        cache_root,
                        validated,
                        mechanism=mechanism,
                    )
                    if cached is None and fingerprint is not None:
                        from ..result_cache import find_result_by_config_snapshot

                        cached = find_result_by_config_snapshot(
                            cache_root, fingerprint, mechanism=mechanism
                        )
                    app.state.preloaded_result = cached
                    # Use the *actual* cache-entry fingerprint (directory name) so
                    # that artifacts_dir_for() resolves correctly in export actions.
                    app.state.preloaded_fingerprint = (
                        cached.get("fingerprint") if cached else None
                    )
                    if cached:
                        meta = cached.get("meta", {})
                        created = meta.get("created_at", 0.0)
                        actual_fp = str(cached.get("fingerprint") or fingerprint or "")
                        logger.info(
                            "Loaded cached simulation result for %s "
                            "(created %.0f s ago, fingerprint %s…)",
                            app.state.preloaded_filename,
                            time.time() - created,
                            actual_fp[:12],
                        )
                        # Surface on the console by default (not only the logger).
                        print(
                            f"[cache] loaded cached result for "
                            f"{app.state.preloaded_filename} "
                            f"(fingerprint {actual_fp[:12]}…) — re-run skipped",
                            flush=True,
                        )
                    elif fingerprint is not None:
                        logger.info(
                            "No valid cache entry found for preloaded config "
                            "(fingerprint %s…). Run the simulation to populate the cache.",
                            fingerprint[:12],
                        )
                else:
                    app.state.preloaded_result = None
                    app.state.preloaded_fingerprint = None
            except Exception as cache_err:
                logger.warning("Cache load at startup failed: %s", cache_err)
                app.state.preloaded_result = None
                app.state.preloaded_fingerprint = None

        except Exception as e:
            logger.error(f"Failed to load preloaded configuration: {e}")

    # Resolve the scenario-inspector store (HDF5): explicit env override wins,
    # else the preloaded config's ``metadata.extra.scenario_store`` resolved
    # relative to the YAML's directory. Enables the GUI Scenario Pane.
    try:
        store_env = os.environ.get("BOULDER_SCENARIO_STORE")
        if store_env and store_env.strip():
            app.state.scenario_store_path = store_env.strip()
        elif app.state.preloaded_config and app.state.preloaded_config_path:
            extra = (app.state.preloaded_config.get("metadata") or {}).get(
                "extra"
            ) or {}
            rel = extra.get("scenario_store")
            base = Path(app.state.preloaded_config_path).resolve().parent
            if rel:
                app.state.scenario_store_path = str((base / rel).resolve())
            elif os.environ.get("BOULDER_SWEEP_MODE"):
                # Sweep mode with no declared store → default next to the config,
                # so pre-computed scenarios (if any) show in the pane.
                stem = Path(app.state.preloaded_config_path).stem
                app.state.scenario_store_path = str(base / f"{stem}_scenarios.h5")
        if app.state.scenario_store_path:
            logger.info("Scenario store enabled: %s", app.state.scenario_store_path)
    except Exception as store_err:  # noqa: BLE001
        logger.warning("Scenario store resolution failed: %s", store_err)
        app.state.scenario_store_path = None

    # ``--run`` (BOULDER_AUTORUN): the frontend auto-starts the run once on load —
    # but only when there is nothing cached to pick up (``--no-cache`` forces it).
    # Decided here, after the cache and scenario store have been resolved.
    _no_cache = bool(os.environ.get("BOULDER_NO_CACHE"))
    _autorun_req = bool(os.environ.get("BOULDER_AUTORUN"))
    if app.state.sweep_default:
        _store = getattr(app.state, "scenario_store_path", None)
        _cache_present = bool(_store and Path(_store).is_file())
    else:
        _cache_present = getattr(app.state, "preloaded_result", None) is not None
    app.state.autorun = _autorun_req and (_no_cache or not _cache_present)
    if _autorun_req and _cache_present and not _no_cache:
        _what = "scenario store" if app.state.sweep_default else "cached result"
        msg = (
            f"[cache] {_what} present — --run picks up from cache "
            f"(use --no-cache to recompute)"
        )
        logger.info(msg)
        print(msg, flush=True)

    # Scenario-focus channel: external tools (e.g. a result dashboard) can drive
    # the open GUI to load a scenario id; tabs subscribe over SSE.
    app.state.scenario_focus_subscribers = set()
    app.state.focused_scenario = None

    logger.info("Boulder API started – plugins loaded, converter ready")
    yield
    # Shutdown: nothing to clean up
    logger.info("Boulder API shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Boulder API",
        description="REST + SSE API for Cantera ReactorNet visualization and simulation",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS – allow the Vite dev server and any local origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev server
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routers
    app.include_router(configs.router, prefix="/api/configs", tags=["configs"])
    app.include_router(
        simulations.router, prefix="/api/simulations", tags=["simulations"]
    )
    app.include_router(mechanisms.router, prefix="/api/mechanisms", tags=["mechanisms"])
    app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
    app.include_router(plugins.router, prefix="/api/plugins", tags=["plugins"])
    app.include_router(
        gui_actions.router, prefix="/api/gui-actions", tags=["gui-actions"]
    )
    app.include_router(scenarios.router, prefix="/api/scenarios", tags=["scenarios"])
    app.include_router(sweep.router, prefix="/api/sweep", tags=["sweep"])
    app.include_router(ui.router, prefix="/api/ui", tags=["ui"])

    # Health check
    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    # Serve React static build in production (if a build exists).
    #
    # Two layouts are supported, in priority order:
    #   1. ``boulder/_frontend`` — the bundled build shipped as package data in
    #      released wheels (vite emits here; see frontend/vite.config.ts).
    #   2. ``<repo>/frontend/dist`` — a local dev build sitting next to the
    #      source tree (editable installs / running from a checkout).
    _pkg_root = Path(__file__).resolve().parent.parent  # .../boulder
    bundled_frontend = _pkg_root / "_frontend"
    dev_frontend = _pkg_root.parent / "frontend" / "dist"
    frontend_dist = bundled_frontend if bundled_frontend.is_dir() else dev_frontend
    if frontend_dist.is_dir():
        from fastapi import HTTPException
        from fastapi.responses import FileResponse

        # Mount hashed JS/CSS chunks BEFORE the SPA catch-all.  If the catch-all
        # runs first, a stale browser bundle requesting a removed chunk (e.g.
        # /assets/SankeyTab-oldhash.js) gets index.html (text/html) instead of
        # 404, which breaks dynamic import with a MIME-type error.
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="assets",
            )

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            if full_path.startswith("assets/"):
                raise HTTPException(status_code=404, detail="Asset not found")
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(frontend_dist / "index.html")

        logger.info(f"Serving React frontend from {frontend_dist}")

    return app


# Module-level app instance for uvicorn
app = create_app()
