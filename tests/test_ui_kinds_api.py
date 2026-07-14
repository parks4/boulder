"""Tests for GET /api/ui/kinds.

Asserts the endpoint lists Boulder's built-in reactor/connection kinds with a
Cantera doc link, and that a plugin-registered kind appears without one.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.cantera_converter import get_plugins  # noqa: E402
from boulder.schema_registry import register_reactor_builder  # noqa: E402


def test_lists_builtin_reactor_and_connection_kinds() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/ui/kinds")
    assert resp.status_code == 200
    body = resp.json()

    reactor_kinds = {r["kind"]: r for r in body["reactors"]}
    connection_kinds = {c["kind"]: c for c in body["connections"]}

    assert "IdealGasReactor" in reactor_kinds
    assert "Reservoir" in reactor_kinds
    assert reactor_kinds["IdealGasReactor"]["doc_url"].startswith(
        "https://cantera.org/"
    )
    assert reactor_kinds["IdealGasReactor"]["description"]

    assert "MassFlowController" in connection_kinds
    assert "PressureController" in connection_kinds
    assert connection_kinds["Valve"]["doc_url"].startswith("https://cantera.org/")


def test_plugin_registered_reactor_kind_has_no_doc_url() -> None:
    plugins = get_plugins()
    register_reactor_builder(
        plugins,
        "_TestPluginReactor",
        builder=lambda converter, node: None,
    )
    try:
        client = TestClient(create_app())
        resp = client.get("/api/ui/kinds")
        assert resp.status_code == 200
        reactor_kinds = {r["kind"]: r for r in resp.json()["reactors"]}
        assert reactor_kinds["_TestPluginReactor"]["doc_url"] is None
    finally:
        del plugins.reactor_builders["_TestPluginReactor"]
        from boulder.schema_registry import _SCHEMA_REGISTRY

        _SCHEMA_REGISTRY.pop("_TestPluginReactor", None)
