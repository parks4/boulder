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


def get_verbose_logger(name: str) -> logging.Logger:
    """Return a logger under ``boulder.*`` with guaranteed console output."""
    _ensure_boulder_package_logging()
    return logging.getLogger(name)
