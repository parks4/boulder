"""Utilities for verbose logging in Boulder."""

import logging
import os
from functools import wraps
from typing import Any, Callable


def get_verbose_level() -> int:
    """Return numeric verbose level from BOULDER_VERBOSE.

    Levels:
    - 0: silent (default)
    - 1: verbose info
    - 2: very verbose (timings, heavy diagnostics)
    """
    raw = os.environ.get("BOULDER_VERBOSE", "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        # Support truthy strings like "true"/"on" -> level 1
        return 1


def is_verbose_mode() -> bool:
    """Check if verbose mode (level >= 1) is enabled via environment variable."""
    return get_verbose_level() >= 1


def is_verbose_level_at_least(level: int) -> bool:
    """Check if current verbose level is at least the specified level."""
    return get_verbose_level() >= int(level)


def get_verbose_logger(name: str) -> logging.Logger:
    """Get a logger configured for verbose output if verbose mode is enabled."""
    logger = logging.getLogger(name)

    if is_verbose_mode() and not logger.handlers:
        # Only configure if verbose mode is on and logger isn't already configured
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # Avoid duplicate logs via root logger
        logger.propagate = False

    return logger


def verbose_print(*args, **kwargs) -> None:
    """Print only if verbose mode is enabled."""
    if is_verbose_mode():
        print(*args, **kwargs)


def log_function_call(logger: logging.Logger) -> Callable:
    """Log function calls in verbose mode."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if is_verbose_mode():
                logger.info(
                    f"Calling {func.__name__} with args={len(args)}, kwargs={list(kwargs.keys())}"
                )
            result = func(*args, **kwargs)
            if is_verbose_mode():
                logger.info(f"Completed {func.__name__}")
            return result

        return wrapper

    return decorator
