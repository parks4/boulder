"""Header status: registration validation and the ``/api/ui/header-links`` listing.

Asserts:
- a status registered with ``add_header_status`` is listed under ``statuses``;
- none is listed when none is registered, and several can coexist;
- ``add_header_link`` links are still listed beside them;
- a ``status_url`` that is not a plain same-origin path (``//host``, ``javascript:``,
  ``http(s)://``, whitespace, backslash, query string, fragment) is rejected.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from boulder.api.routes import ui
from boulder.cantera_converter import BoulderPlugins


def _get(monkeypatch, plugins):
    monkeypatch.setattr("boulder.cantera_converter.get_plugins", lambda: plugins)
    app = FastAPI()
    app.include_router(ui.router, prefix="/api/ui")
    return TestClient(app).get("/api/ui/header-links").json()


def test_no_status_by_default(monkeypatch):
    assert _get(monkeypatch, BoulderPlugins())["statuses"] == []


def test_registered_statuses_are_listed_beside_links(monkeypatch):
    plugins = BoulderPlugins()
    plugins.add_header_link("Reports", "/reports")
    plugins.add_header_status("/api/host/status")
    plugins.add_header_status("/api/host/other")
    body = _get(monkeypatch, plugins)
    assert body["statuses"] == [
        {"status_url": "/api/host/status"},
        {"status_url": "/api/host/other"},
    ]
    assert body["links"][0]["href"] == "/reports"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "status",
        "//evil.example/x",
        "javascript:alert(1)",
        "http://example.com/status",
        "https://example.com/status",
        "/a b",
        "/a\tb",
        "/a\\b",
        "/status?x=1",
        "/status#frag",
        None,
    ],
)
def test_invalid_status_url_rejected(url):
    with pytest.raises(ValueError):
        BoulderPlugins().add_header_status(url)
