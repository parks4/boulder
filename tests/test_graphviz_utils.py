"""Tests for Graphviz PATH discovery helpers."""

from __future__ import annotations

import os
import shutil
import sys

import pytest

from boulder.graphviz_utils import ensure_graphviz_on_path


def test_ensure_graphviz_on_path_restores_dot_from_env_prefix():
    """Asserts ensure_graphviz_on_path prepends the env bin dir when dot is absent from PATH."""
    conda_prefix = os.environ.get("CONDA_PREFIX") or sys.prefix
    lib_bin = os.path.join(conda_prefix, "Library", "bin", "dot.exe")
    unix_bin = os.path.join(conda_prefix, "bin", "dot")
    if not (os.path.isfile(lib_bin) or os.path.isfile(unix_bin)):
        pytest.skip("graphviz dot not installed in this environment")

    old_path = os.environ.get("PATH")
    old_prefix = os.environ.get("CONDA_PREFIX")
    os.environ["PATH"] = os.pathsep.join(
        p for p in (old_path or "").split(os.pathsep) if "miniconda3" not in p and "conda" not in p
    )
    os.environ["CONDA_PREFIX"] = conda_prefix
    try:
        assert shutil.which("dot") is None
        dot_path = ensure_graphviz_on_path()
        assert dot_path is not None
        assert shutil.which("dot") is not None
    finally:
        if old_path is not None:
            os.environ["PATH"] = old_path
        if old_prefix is not None:
            os.environ["CONDA_PREFIX"] = old_prefix
        elif "CONDA_PREFIX" in os.environ:
            del os.environ["CONDA_PREFIX"]


def test_network_diagram_works_after_path_restore():
    """Asserts NetworkPlugin can render when dot is restored from the active env prefix."""
    conda_prefix = os.environ.get("CONDA_PREFIX") or sys.prefix
    lib_bin = os.path.join(conda_prefix, "Library", "bin", "dot.exe")
    unix_bin = os.path.join(conda_prefix, "bin", "dot")
    if not (os.path.isfile(lib_bin) or os.path.isfile(unix_bin)):
        pytest.skip("graphviz dot not installed in this environment")

    import cantera as ct

    from boulder.network_plugin import NetworkPlugin

    old_path = os.environ.get("PATH")
    old_prefix = os.environ.get("CONDA_PREFIX")
    os.environ["PATH"] = os.pathsep.join(
        p for p in (old_path or "").split(os.pathsep) if "miniconda3" not in p and "conda" not in p
    )
    os.environ["CONDA_PREFIX"] = conda_prefix
    try:
        gas = ct.Solution("gri30.yaml")
        reactor = ct.IdealGasReactor(gas, clone=False)
        network = ct.ReactorNet([reactor])
        plugin = NetworkPlugin()
        encoded_image, error_message = plugin._generate_network_diagram(network)
        assert encoded_image is not None, error_message
        assert error_message is None
    finally:
        if old_path is not None:
            os.environ["PATH"] = old_path
        if old_prefix is not None:
            os.environ["CONDA_PREFIX"] = old_prefix
        elif "CONDA_PREFIX" in os.environ:
            del os.environ["CONDA_PREFIX"]
