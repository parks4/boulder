"""Utilities for verbose logging in Boulder."""

import logging
import os
import threading

_lock = threading.Lock()
_boulder_logging_configured = False


def is_verbose_mode() -> bool:
    """Check if verbose mode is enabled via environment variable."""
    return os.environ.get("BOULDER_VERBOSE", "").strip() == "1"


def _ensure_boulder_package_logging() -> None:
    """Configure the ``boulder`` package logger once for console output.

    Without this, ``boulder.*`` loggers propagate to the root logger (WARNING),
    so INFO progress lines from the simulation worker and staged solver were
    invisible in the default server console.  INFO is always emitted; set
    ``BOULDER_VERBOSE=1`` for DEBUG-level detail.
    """
    global _boulder_logging_configured
    with _lock:
        pkg = logging.getLogger("boulder")
        if not _boulder_logging_configured:
            if not pkg.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
                handler.setFormatter(formatter)
                pkg.addHandler(handler)
            pkg.propagate = False
            _boulder_logging_configured = True
        pkg.setLevel(logging.DEBUG if is_verbose_mode() else logging.INFO)


def ensure_boulder_console_logging() -> None:
    """Enable INFO (or DEBUG if verbose) console output for all ``boulder.*`` loggers.

    Call once from the ASGI lifespan or CLI so package loggers work before any
    module imports :func:`get_verbose_logger`.
    """
    _ensure_boulder_package_logging()


#: Endpoints the frontend polls on a timer while a run is in flight. Their
#: access lines say nothing about the run and, at one request per second,
#: they bury everything that does -- which is how a long solve ends up with
#: no readable log at all under ``--verbose``.
POLLED_ENDPOINTS: tuple[str, ...] = (
    "/api/sweep/status",
    "/api/scenarios/focus/stream",
    "/api/simulations/cached",
)

#: Set to 1 to keep them, e.g. when debugging the polling itself.
_KEEP_POLLING_LOGS_ENV = "BOULDER_LOG_POLLING"


class _PollingAccessFilter(logging.Filter):
    """Drop uvicorn access lines for the timer-driven endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(endpoint in message for endpoint in POLLED_ENDPOINTS)


def quiet_polling_access_logs() -> None:
    """Stop timer-driven polling from burying the access log.

    Installed from the ASGI lifespan, which runs after uvicorn has configured
    its own loggers, so the filter is not overwritten. Idempotent, and a no-op
    when ``BOULDER_LOG_POLLING=1``.
    """
    if os.environ.get(_KEEP_POLLING_LOGS_ENV) == "1":
        return
    access_logger = logging.getLogger("uvicorn.access")
    if any(isinstance(f, _PollingAccessFilter) for f in access_logger.filters):
        return
    access_logger.addFilter(_PollingAccessFilter())


def get_verbose_logger(name: str) -> logging.Logger:
    """Return a logger under ``boulder.*`` with guaranteed console output."""
    _ensure_boulder_package_logging()
    return logging.getLogger(name)
