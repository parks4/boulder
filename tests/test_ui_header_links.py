"""Header links: registration validation and the ``/api/ui/header-links`` endpoint.

Asserts:
- a link registered with ``add_header_link`` is served by the endpoint;
- no link is served when none is registered;
- empty labels and non-path / non-http(s) hrefs (``javascript:``, ``//host``) are rejected.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from boulder.api.routes import ui
from boulder.cantera_converter import BoulderPlugins


def _client(monkeypatch, plugins):
    monkeypatch.setattr("boulder.cantera_converter.get_plugins", lambda: plugins)
    app = FastAPI()
    app.include_router(ui.router, prefix="/api/ui")
    return TestClient(app)


def test_endpoint_empty_without_registration(monkeypatch):
    resp = _client(monkeypatch, BoulderPlugins()).get("/api/ui/header-links")
    assert resp.json() == {"links": []}


def test_registered_link_is_served(monkeypatch):
    plugins = BoulderPlugins()
    plugins.add_header_link("Reports", "/reports", tooltip="Past runs", new_tab=True)
    plugins.add_header_link("Docs", "https://example.com/docs")
    links = _client(monkeypatch, plugins).get("/api/ui/header-links").json()["links"]
    assert links[0] == {
        "label": "Reports",
        "href": "/reports",
        "tooltip": "Past runs",
        "new_tab": True,
        "order": 10,
    }
    assert links[1]["href"] == "https://example.com/docs"


@pytest.mark.parametrize(
    "label, href",
    [
        ("", "/reports"),
        ("  ", "/reports"),
        ("Reports", "javascript:alert(1)"),
        ("Reports", "JavaScript:alert(1)"),
        ("Reports", "//evil.example/x"),
        ("Reports", "reports"),
        ("Reports", "data:text/html,x"),
        ("Reports", ""),
        ("Reports", "/\\evil"),
        ("Reports", "/a\tb"),
        ("Reports", "/a\nb"),
        ("Reports", "/a b"),
    ],
)
def test_invalid_link_rejected(label, href):
    with pytest.raises(ValueError):
        BoulderPlugins().add_header_link(label, href)


def test_link_order_defaults_to_10_and_is_served(monkeypatch):
    """A link's integer ``order`` is served; it defaults to 10 (after the toggle)."""
    plugins = BoulderPlugins()
    plugins.add_header_link("A", "/a")
    plugins.add_header_link("B", "/b", order=-5)
    links = _client(monkeypatch, plugins).get("/api/ui/header-links").json()["links"]
    assert [link["order"] for link in links] == [10, -5]


@pytest.mark.parametrize("order", ["1", 1.5, True, None])
def test_non_integer_link_order_rejected(order):
    """A non-int (or bool) ``order`` raises ValueError like any bad link field."""
    with pytest.raises(ValueError, match="order"):
        BoulderPlugins().add_header_link("Reports", "/reports", order=order)
