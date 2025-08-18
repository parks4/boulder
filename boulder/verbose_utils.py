"""Utilities for verbose logging in Boulder."""

import logging
import os
from functools import wraps
from typing import Any, Callable


def is_verbose_mode() -> bool:
    """Check if verbose mode is enabled via environment variable."""
    return os.environ.get("BOULDER_VERBOSE", "").strip() == "1"


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

    return logger


def verbose_print(*args, **kwargs) -> None:
    """Print only if verbose mode is enabled."""
    if is_verbose_mode():
        print(*args, **kwargs)


def log_function_call(logger: logging.Logger) -> Callable:
    """Decorator to log function calls in verbose mode."""

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
