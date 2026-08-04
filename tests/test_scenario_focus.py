"""Tests for the scenario-focus remote-control channel.

``POST /api/scenarios/focus`` validates the id against the active store and
broadcasts it; ``GET /api/scenarios/focus/stream`` (SSE) emits the current focus
to a (possibly late-joining) subscriber. These let an external dashboard drive
the open GUI to load a scenario.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("h5py")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402


def _make_store(store_dir: Path, ids: list[str], identity: str) -> None:
    """One entry file per id, written the way a real solve writes them."""
    from boulder import scenario_store

    for order, sid in enumerate(ids):
        scenario_store.write_entry(
            store_dir,
            sid,
            gui_payload={"status": "complete", "times": [], "reactors_series": {}},
            mechanism="gri30.yaml",
            fingerprint=f"fp-{sid}",
            identity=identity,
            order=order,
        )


@contextmanager
def _client_with_store(tmp_path: Path, ids: list[str]):
    """Yield ``(client, app)`` with the store wired after startup.

    The app handle (not ``client.app``, which is typed as the bare ASGI callable)
    gives typed access to ``app.state``.
    """
    from boulder import scenario_store
    from boulder.runset import resolve_store_dir

    cfg = tmp_path / "model.yaml"
    cfg.write_text("metadata: {}\n", encoding="utf-8")
    app = create_app()
    with TestClient(app) as client:
        # Set *after* startup — the lifespan resets the preloaded state on entry.
        # The store location is derived from the config path, not cached on
        # app.state, so pointing at the config is all that's needed.
        app.state.preloaded_config_path = str(cfg)
        app.state.preloaded_raw = {"metadata": {}}
        store_dir = resolve_store_dir({}, cfg)
        assert store_dir is not None
        _make_store(store_dir, ids, scenario_store.config_identity(cfg))
        yield client, app


def test_focus_valid_id_broadcasts(tmp_path: Path) -> None:
    with _client_with_store(tmp_path, ["s1", "s2"]) as (client, app):
        resp = client.post("/api/scenarios/focus", json={"scenario_id": "s2"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "scenario_id": "s2"}
        assert app.state.focused_scenario == "s2"


def test_focus_unknown_id_404(tmp_path: Path) -> None:
    with _client_with_store(tmp_path, ["s1"]) as (client, _app):
        resp = client.post("/api/scenarios/focus", json={"scenario_id": "nope"})
        assert resp.status_code == 404
        assert "nope" in resp.json()["detail"]


def test_focus_no_store_404(tmp_path: Path) -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.scenario_store_path = None
        resp = client.post("/api/scenarios/focus", json={"scenario_id": "s1"})
        assert resp.status_code == 404


def test_focus_broadcasts_to_subscribers(tmp_path: Path) -> None:
    """A POST /focus pushes the id onto every registered SSE subscriber queue.

    Avoids consuming the (infinite) SSE body via TestClient — the stream's
    behaviour is exercised end-to-end by the Playwright check instead.
    """
    with _client_with_store(tmp_path, ["s1", "s2"]) as (client, app):
        queue: asyncio.Queue = asyncio.Queue()
        app.state.scenario_focus_subscribers.add(queue)

        assert (
            client.post("/api/scenarios/focus", json={"scenario_id": "s2"}).status_code
            == 200
        )

        assert queue.get_nowait() == "s2"
