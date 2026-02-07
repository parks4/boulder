"""FastAPI application entry point for Boulder.

This module creates the FastAPI app, configures CORS middleware,
registers all API routes, and serves the React frontend in production.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import configs, graph, mechanisms, plugins, simulations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    # Startup: register built-in plugins and create global converter
    from ..cantera_converter import DualCanteraConverter
    from ..network_plugin import register_network_plugin

    register_network_plugin()
    # Store a shared converter on the app state for routes to access
    # Handle potential Unicode issues on Windows by creating with a safe default
    try:
        app.state.converter = DualCanteraConverter()
    except (UnicodeEncodeError, ValueError) as e:
        logger.warning(f"Failed to initialize converter with plugins: {e}")
        logger.warning("Starting with minimal plugin support")
        # Create a basic converter without problematic plugins
        app.state.converter = DualCanteraConverter()
    
    # Load initial configuration from environment variable if provided
    env_config_path = os.environ.get("BOULDER_CONFIG_PATH") or os.environ.get(
        "BOULDER_CONFIG"
    )
    app.state.preloaded_config = None
    app.state.preloaded_yaml = None
    app.state.preloaded_filename = None
    
    if env_config_path and env_config_path.strip():
        try:
            from ..config import (
                load_config_file_with_py_support_and_comments,
                normalize_config,
                validate_config,
            )
            
            cleaned = env_config_path.strip()
            verbose = os.environ.get("BOULDER_VERBOSE") == "1"
            
            if verbose:
                logger.info(f"Loading preloaded configuration from: {cleaned}")
            
            config, original_yaml, actual_yaml_path = (
                load_config_file_with_py_support_and_comments(cleaned, verbose)
            )
            normalized = normalize_config(config)
            validated = validate_config(normalized)
            
            app.state.preloaded_config = validated
            app.state.preloaded_yaml = original_yaml
            app.state.preloaded_filename = os.path.basename(actual_yaml_path)
            
            logger.info(f"Preloaded configuration: {app.state.preloaded_filename}")
        except Exception as e:
            logger.error(f"Failed to load preloaded configuration: {e}")
    
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

    # Health check
    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    # Serve React static build in production (if dist/ exists)
    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        # Serve index.html for all non-API routes (SPA fallback)
        from fastapi.responses import FileResponse

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(frontend_dist / "index.html")

        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")
        logger.info(f"Serving React frontend from {frontend_dist}")

    return app


# Module-level app instance for uvicorn
app = create_app()
