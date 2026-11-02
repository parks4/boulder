"""Importing Boulder modules must not configure logging for the host."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_importing_boulder_modules_leaves_boulder_logger_untouched() -> None:
    """``propagate`` stays True, no handler is added, level stays unset.

    Run in a fresh interpreter so earlier imports in the test session cannot
    mask the import-time side effect. ``boulder.api.main`` pulls in the
    converter, sankey and worker modules.
    """
    repo_root = Path(__file__).resolve().parent.parent
    script = """
import logging
import boulder.api.main
log = logging.getLogger("boulder")
assert log.propagate is True and not log.handlers and log.level == 0, (
    log.propagate, log.handlers, log.level)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root), "BOULDER_VERBOSE": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
