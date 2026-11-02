"""Pytest configuration for Boulder tests."""

import logging

import pytest

from boulder import verbose_utils


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")


@pytest.fixture(autouse=True)
def _restore_boulder_logger_state():
    """Undo the console logging an app lifespan or CLI call sets up in-process.

    ``ensure_boulder_console_logging`` (run by the ASGI lifespan and the CLI
    entry) sets ``propagate = False`` on the ``boulder`` logger. Left in place
    it hides later tests' records from ``caplog``.
    """
    pkg = logging.getLogger("boulder")
    saved = (pkg.propagate, list(pkg.handlers), pkg.level)
    yield
    pkg.propagate = saved[0]
    pkg.handlers[:] = saved[1]
    pkg.setLevel(saved[2])
    verbose_utils._boulder_logging_configured = False
