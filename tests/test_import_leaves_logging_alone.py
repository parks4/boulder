"""Importing Boulder modules must not configure logging for the host."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_importing_boulder_modules_leaves_boulder_logger_untouched() -> None:
    """``propagate`` stays True, no handler is added, level stays unset.

    Run in a fresh interpreter so earlier imports in the test session cannot
    mask the import-time side effect.
    """
    repo_root = Path(__file__).resolve().parent.parent
    script = """
import logging
before = logging.getLogger("boulder")
state = (before.propagate, list(before.handlers), before.level)
import boulder.cantera_converter, boulder.sankey, boulder.simulation_worker
import boulder.verbose_utils
after = logging.getLogger("boulder")
assert (after.propagate, list(after.handlers), after.level) == state, (
    after.propagate, after.handlers, after.level)
assert after.propagate is True
assert not after.handlers
assert boulder.verbose_utils.is_verbose_mode() is False
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
