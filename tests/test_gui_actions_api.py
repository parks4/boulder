"""Tests for the GUI action plugin API routes.

Asserts that registered GUI actions are listed via GET /api/gui-actions and
that POST /api/gui-actions/{id}/run returns a downloadable file response.
"""

from __future__ import annotations

import time
from typing import Any, Dict

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
from boulder.result_cache import CACHE_VERSION, save_result  # noqa: E402

SIMPLE_CONFIG: Dict[str, Any] = {
    "nodes": [{"id": "r1", "type": "IdealGasReactor", "properties": {"T": 1000}}],
    "connections": [],
    "settings": {"solver": {"kind": "steady_state"}},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
}

SIMPLE_PAYLOAD: Dict[str, Any] = {
    "status": "complete",
    "is_complete": True,
    "error_message": None,
    "times": [0.0],
    "reactors_series": {"r1": {"T": [1000.0], "P": [101325.0], "X": {}}},
    "reactor_reports": {},
    "connection_reports": {},
    "code_str": "# generated",
    "summary": [],
    "sankey_links": None,
    "sankey_nodes": None,
    "elapsed_time": 1.23,
    "updated_nodes": None,
    "updated_connections": None,
}


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
        assert echo["description"] is None

    def test_list_actions_includes_description_when_overridden(self):
        """An action overriding `description` exposes it via GET /api/gui-actions."""

        class _DescribedAction(GuiActionPlugin):
            @property
            def action_id(self) -> str:
                return "test_described_action"

            @property
            def label(self) -> str:
                return "Described Export"

            @property
            def description(self) -> str:
                return "Explains what this button downloads."

            def run(self, context: GuiActionContext) -> GuiActionResult:
                return GuiActionResult(content=b"ok", filename="out.txt")

        register_gui_action(_DescribedAction())
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/gui-actions")
            assert resp.status_code == 200
            item = next(i for i in resp.json() if i["id"] == "test_described_action")
            assert item["description"] == "Explains what this button downloads."

    def test_list_actions_for_context_reflects_uploaded_config(self):
        """POST /api/gui-actions lists actions for a browser-uploaded config.

        Asserts that an action gated on a config key (here ``export:``, via
        a custom ``is_listed``) is listed when that key is present in
        ``body.config``, even though the server's startup preload has no
        config at all (``app.state.preloaded_config`` stays ``None``) —
        reproducing the "Upload Config" flow where the server was launched
        without a YAML argument.
        """

        class _ExportGatedAction(GuiActionPlugin):
            @property
            def action_id(self) -> str:
                return "test_export_gated_action"

            @property
            def label(self) -> str:
                return "Gated Export"

            def is_listed(self, context: GuiActionContext) -> bool:
                return bool(
                    isinstance(context.config, dict) and "export" in context.config
                )

            def run(self, context: GuiActionContext) -> GuiActionResult:
                return GuiActionResult(content=b"ok", filename="out.txt")

        register_gui_action(_ExportGatedAction())
        app = create_app()
        with TestClient(app) as client:
            assert app.state.preloaded_config is None

            # GET (no context) must not see the gated action.
            get_resp = client.get("/api/gui-actions")
            assert get_resp.status_code == 200
            assert all(
                item["id"] != "test_export_gated_action" for item in get_resp.json()
            )

            # POST with the uploaded config must see it.
            post_resp = client.post(
                "/api/gui-actions",
                json={"config": {"export": {"calc_note": "x.xlsx"}}},
            )
            assert post_resp.status_code == 200
            listed_ids = [item["id"] for item in post_resp.json()]
            assert "test_export_gated_action" in listed_ids

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


class TestGuiActionCacheContext:
    def test_build_context_matches_check_cache(self, tmp_path):
        """_build_context and check-cache agree on has_cached_result for body.config."""
        from boulder.api.routes.gui_actions import _build_context
        from boulder.api.routes.simulations import normalize_config_for_fingerprint
        from boulder.result_cache import (
            compute_fingerprint,
            resolve_mechanism_for_fingerprint,
        )

        yaml_path = tmp_path / "model.yaml"
        yaml_path.write_text("nodes: []\n", encoding="utf-8")
        # Write the entry the way a real run does: the worker fingerprints
        # the normalized (default-group-synthesized) config, not the raw one.
        snapshot = normalize_config_for_fingerprint(SIMPLE_CONFIG)
        mechanism = resolve_mechanism_for_fingerprint(snapshot)
        fingerprint = compute_fingerprint(snapshot, mechanism=mechanism)
        save_result(
            cache_root=tmp_path / ".boulder-cache",
            fingerprint=fingerprint,
            gui_payload=SIMPLE_PAYLOAD,
            config_snapshot=snapshot,
        )

        app = create_app()
        with TestClient(app) as client:
            app.state.preloaded_config_path = str(yaml_path)
            app.state.preloaded_result = None
            app.state.preloaded_fingerprint = None

            body = {
                "config": SIMPLE_CONFIG,
                "mechanism": "gri30.yaml",
            }
            cache_resp = client.post("/api/simulations/check-cache", json=body)
            assert cache_resp.json()["cached"] is True

            from boulder.api.routes.gui_actions import GuiActionRunRequest

            class _Req:
                app = client.app

            ctx = _build_context(_Req(), GuiActionRunRequest(**body))
            assert ctx.has_cached_result is True
            assert ctx.cache_fingerprint is not None

    def test_build_context_rejects_stale_preloaded_fingerprint(self, tmp_path):
        """Edited body.config must not inherit startup cache state."""
        from boulder.api.routes.gui_actions import GuiActionRunRequest, _build_context

        yaml_path = tmp_path / "model.yaml"
        yaml_path.write_text("nodes: []\n", encoding="utf-8")
        fingerprint = "d" * 64
        cached = {
            "fingerprint": fingerprint,
            "gui_payload": SIMPLE_PAYLOAD,
            "config_snapshot": SIMPLE_CONFIG,
            "meta": {"cache_version": CACHE_VERSION, "created_at": time.time()},
            "artifacts_dir": tmp_path / ".boulder-cache" / fingerprint / "artifacts",
        }

        edited_config = dict(SIMPLE_CONFIG)
        edited_config["nodes"] = [
            {"id": "r2", "type": "IdealGasReactor", "properties": {"T": 2000}}
        ]

        app = create_app()
        with TestClient(app) as client:
            app.state.preloaded_config_path = str(yaml_path)
            app.state.preloaded_result = cached
            app.state.preloaded_fingerprint = fingerprint

            class _Req:
                app = client.app

            ctx = _build_context(
                _Req(),
                GuiActionRunRequest(config=edited_config, mechanism="gri30.yaml"),
            )
            assert ctx.has_cached_result is False
            assert ctx.cache_fingerprint is not None
