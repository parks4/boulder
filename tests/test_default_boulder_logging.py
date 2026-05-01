"""Tests that Boulder emits INFO logs without BOULDER_VERBOSE.

Asserts that ``ensure_boulder_console_logging`` / ``get_verbose_logger`` attach
a handler so simulation and staged-solve progress is visible on stderr by
default (previously only WARNING reached the root logger).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_ensure_boulder_console_logging_emits_info_without_verbose_env() -> None:
    """Asserts INFO lines reach stderr when BOULDER_VERBOSE is unset."""
    repo_root = Path(__file__).resolve().parent.parent
    marker = "boulder-logging-marker-info"
    script = f"""
import logging
import os
os.environ.pop("BOULDER_VERBOSE", None)
from boulder.verbose_utils import ensure_boulder_console_logging
ensure_boulder_console_logging()
log = logging.getLogger("boulder.test_marker")
log.info("{marker}")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert marker in proc.stderr, proc.stderr + proc.stdout


def test_get_verbose_logger_emits_info_without_verbose_env() -> None:
    """Asserts ``get_verbose_logger`` configures the package so INFO is printed."""
    repo_root = Path(__file__).resolve().parent.parent
    marker = "boulder-verbose-logger-marker"
    script = f"""
import os
os.environ.pop("BOULDER_VERBOSE", None)
from boulder.verbose_utils import get_verbose_logger
log = get_verbose_logger("boulder.test_verbose_logger")
log.info("{marker}")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert marker in proc.stderr, proc.stderr + proc.stdout
