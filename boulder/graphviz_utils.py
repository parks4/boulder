"""Helpers for locating Graphviz binaries bundled with the active Python env."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_DOT_NAMES = ("dot.exe", "dot") if os.name == "nt" else ("dot",)


def _graphviz_bin_dirs() -> list[Path]:
    """Return candidate directories that may contain the ``dot`` executable."""
    prefixes: list[Path] = []
    conda_prefix = os.environ.get("CONDA_PREFIX", "").strip()
    if conda_prefix:
        prefixes.append(Path(conda_prefix))
    prefixes.append(Path(sys.prefix))

    dirs: list[Path] = []
    seen: set[Path] = set()
    for prefix in prefixes:
        for sub in ("Library/bin", "bin"):
            candidate = (prefix / sub).resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            dirs.append(candidate)
    return dirs


def _find_dot_executable() -> Path | None:
    for directory in _graphviz_bin_dirs():
        for name in _DOT_NAMES:
            dot_path = directory / name
            if dot_path.is_file():
                return dot_path
    return None


def ensure_graphviz_on_path() -> Path | None:
    """Prepend the Graphviz binary directory to ``PATH`` when ``dot`` is missing.

    Conda installs ``dot`` under ``$CONDA_PREFIX/Library/bin`` (Windows) or
    ``$CONDA_PREFIX/bin`` (Unix).  GUI launches and IDE terminals often run
    Python without those directories on ``PATH`` even though ``python-graphviz``
    is installed in the active environment.

    Returns
    -------
    Path | None
        Resolved path to ``dot`` when found, else ``None``.
    """
    found = shutil.which("dot")
    if found:
        return Path(found)

    dot_path = _find_dot_executable()
    if dot_path is None:
        return None

    directory = str(dot_path.parent)
    path = os.environ.get("PATH", "")
    if directory not in path.split(os.pathsep):
        os.environ["PATH"] = directory + os.pathsep + path
    return dot_path.resolve()
