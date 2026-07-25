"""Render the live network graph to a PNG, headlessly.

Drives a headless Chromium (via the optional ``playwright`` dependency)
against a throwaway Boulder web server to capture the same Cytoscape graph
the interactive app renders — just the graph canvas (light background,
independent of the app's current theme and current pan/zoom), not the
surrounding page chrome.

Requires the optional ``playwright`` extra::

    pip install boulder[playwright]
    playwright install chromium

The one exported entry point, :func:`render_network_schema_png`, is a plain
function (config path in, PNG path out) with no CLI-specific state, so it's
reusable directly from other Python code — e.g. a Sphinx doc build wanting a
network diagram for a gallery, or Bloc's Calculation Note export wanting a
network image when running headless with no browser to capture from.
"""

from __future__ import annotations

import asyncio
import base64
import os
import threading
from pathlib import Path

_INSTALL_HINT = (
    "Rendering the network graph requires the optional 'playwright' dependency, "
    "which isn't installed.\n"
    "Install it with:\n"
    "    pip install boulder[playwright]\n"
    "    playwright install chromium\n"
)


class PlaywrightNotInstalledError(RuntimeError):
    """Playwright's Python package or its browser binaries aren't available."""


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PlaywrightNotInstalledError(_INSTALL_HINT) from exc
    return sync_playwright


def render_network_schema_png(
    config_path: "str | Path",
    output_path: "str | Path",
    *,
    host: str = "127.0.0.1",
    timeout: float = 30.0,
    bg: str = "#ffffff",
    scale: float = 2.0,
) -> Path:
    """Render *config_path*'s network graph to a PNG at *output_path*.

    Spins up a throwaway Boulder web server (no browser window opened for a
    human — Playwright drives a headless one instead), waits for it to
    accept connections, navigates to it, waits for the Cytoscape graph to
    finish initializing *and* populate its elements (``window.__boulderCy``
    exists immediately on mount, but its nodes/edges load asynchronously
    right after), and captures
    ``cy.png({bg, full: true, scale, output: "base64"})`` — the whole graph
    regardless of its current pan/zoom, not a screenshot of the page.

    Parameters
    ----------
    config_path : str or Path
        YAML config to preload (same as the ``boulder <file>`` CLI arg).
    output_path : str or Path
        Where to write the PNG. Parent directories are created as needed.
    host : str
        Interface to bind the throwaway server to.
    timeout : float
        Seconds to wait for the server to start and for the graph to
        initialize (each phase gets its own budget of this length).
    bg : str
        Background color forced on the capture, regardless of the app's
        current light/dark theme.
    scale : float
        Resolution multiplier passed to ``cy.png()``.

    Returns
    -------
    Path
        *output_path*, for chaining.

    Raises
    ------
    PlaywrightNotInstalledError
        Playwright isn't installed — see the module docstring, or the
        exception message, for how to fix.
    FileNotFoundError
        *config_path* doesn't exist.
    TimeoutError
        The server didn't start, or the graph didn't initialize, within
        *timeout* seconds.
    """
    sync_playwright = _require_playwright()

    config_path = Path(config_path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from .cli import find_available_port, wait_for_port

    port = find_available_port(host, 8100)

    # BOULDER_CONFIG_PATH is process-wide env state (create_app()'s lifespan
    # hook reads it, same mechanism the CLI itself uses), so it must be
    # restored afterward — otherwise this call leaks a stale config path to
    # any other code sharing the interpreter (a second render call for a
    # different config, or unrelated code in the same process/test run that
    # creates its own app expecting no preload).
    _prev_config_path = os.environ.get("BOULDER_CONFIG_PATH")
    os.environ["BOULDER_CONFIG_PATH"] = str(config_path)
    server, thread = _start_server_thread(host, port)
    try:
        try:
            if not wait_for_port(host, port, timeout=timeout):
                raise TimeoutError(
                    f"Boulder server did not start within {timeout:.0f}s "
                    f"(preloading {config_path})"
                )
        finally:
            # The app has already read the env var into app.state by the
            # time the socket accepts connections (ASGI lifespan startup
            # runs before uvicorn starts serving) — safe to restore now,
            # before the (potentially slow) browser step below.
            if _prev_config_path is None:
                os.environ.pop("BOULDER_CONFIG_PATH", None)
            else:
                os.environ["BOULDER_CONFIG_PATH"] = _prev_config_path

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(f"http://{host}:{port}", wait_until="networkidle")
                # The cy instance exists as soon as the graph component mounts,
                # but its elements populate asynchronously right after (the
                # preloaded config loads, then the graph re-renders with real
                # nodes/edges) — wait for actual elements, not just the
                # instance, or an empty/blank capture is a real race.
                page.wait_for_function(
                    "() => !!window.__boulderCy && window.__boulderCy.elements().length > 0",
                    timeout=timeout * 1000,
                )
                b64 = page.evaluate(
                    "([bg, scale]) => window.__boulderCy.png("
                    "{bg, full: true, scale, output: 'base64'})",
                    [bg, scale],
                )
                output_path.write_bytes(base64.b64decode(b64))
            finally:
                browser.close()
    finally:
        _stop_server_thread(server, thread)

    return output_path


def _start_server_thread(host: str, port: int):
    """Start a Boulder ASGI server on a background thread.

    Preloads whatever config BOULDER_CONFIG_PATH points to — the caller is
    responsible for setting (and restoring) that env var, since create_app()
    takes no kwargs and reads it via its lifespan hook instead (same
    mechanism the CLI itself uses).
    """
    import uvicorn

    from .api.main import create_app

    app = create_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning")
    )

    def _run() -> None:
        asyncio.run(server.serve())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return server, thread


def _stop_server_thread(server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)
