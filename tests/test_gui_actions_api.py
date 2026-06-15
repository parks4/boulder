"""Tests for the GUI action plugin API routes.

Asserts that registered GUI actions are listed via GET /api/gui-actions and
that POST /api/gui-actions/{id}/run returns a downloadable file response.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.gui_actions import (  # noqa: E402
    GuiActionContext,
    GuiActionPlugin,
    GuiActionResult,
    get_gui_action_registry,
    register_gui_action,
)


class _EchoAction(GuiActionPlugin):
    """Test action that echoes the config filename in the download payload."""

    @property
    def action_id(self) -> str:
        return "test_echo_action"

    @property
    def label(self) -> str:
        return "Echo Export"

    def run(self, context: GuiActionContext) -> GuiActionResult:
        name = context.filename or "unknown"
        return GuiActionResult(
            content=f"echo:{name}".encode(),
            filename="echo.txt",
            media_type="text/plain",
        )


@pytest.fixture
def echo_action_client():
    """Test client with a registered echo GUI action."""
    register_gui_action(_EchoAction())
    app = create_app()
    with TestClient(app) as client:
        yield client


class TestGuiActionsApi:
    def test_list_actions(self, echo_action_client: TestClient):
        """GET /api/gui-actions returns registered action metadata."""
        resp = echo_action_client.get("/api/gui-actions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        echo = next(item for item in data if item["id"] == "test_echo_action")
        assert echo["label"] == "Echo Export"
        assert echo["requires_simulation"] is False

    def test_run_action(self, echo_action_client: TestClient):
        """POST /api/gui-actions/{id}/run returns attachment with filename."""
        resp = echo_action_client.post(
            "/api/gui-actions/test_echo_action/run",
            json={"filename": "demo.yaml"},
        )
        assert resp.status_code == 200
        assert resp.content == b"echo:demo.yaml"
        assert resp.headers["content-type"].startswith("text/plain")
        assert 'filename="echo.txt"' in resp.headers["content-disposition"]

    def test_run_unknown_action(self):
        """Unknown action IDs return 404."""
        app = create_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/gui-actions/missing_action/run",
                json={},
            )
            assert resp.status_code == 404

    def test_registry_dedupes_action_ids(self):
        """Re-registering the same action ID is a no-op."""
        registry = get_gui_action_registry()
        before = sum(
            1 for action in registry.actions if action.action_id == "test_echo_action"
        )
        register_gui_action(_EchoAction())
        after = sum(
            1 for action in registry.actions if action.action_id == "test_echo_action"
        )
        assert after == before
