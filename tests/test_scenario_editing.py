"""Tests for scenario authoring: POST/PATCH/DELETE /api/scenarios*.

Unlike the read routes in ``test_scenario_focus.py`` (which serve precomputed
HDF5 trajectories), these cover the input side of the Scenario Pane's
create/edit workflow. Every mutating route here is a pure, stateless
transform: the caller sends the *current* overlays map and gets back the
*new* one — nothing is written to disk or kept on ``app.state`` between
requests (see ``boulder/scenario_editor.py``'s module docstring). Tests fetch
the config's startup `scenarios:` block once via `GET /api/scenarios`
(mirroring what the frontend's `scenarioStore` does on load), then thread the
returned `overlays` through each call exactly like the frontend would.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402

_BASE_YAML = """\
metadata:
  description: "test config"  # keep this comment
phases:
  gas:
    mechanism: gri30.yaml
network:
  - id: feed
    Reservoir:
      temperature: 298.15
      pressure: 101325
      composition: "CH4:1"
scenarios:
  base_case:
    metadata:
      description: "Base Case"
    network:
      - id: feed
        Reservoir:
          temperature: 320.0
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_BASE_YAML, encoding="utf-8")
    return cfg


def _client_with_config(cfg_path: Path):
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg_path)
    return client, app


def _authored_overlays(client: TestClient) -> Dict[str, Any]:
    """Return the config's startup `scenarios:` block -- what `scenarioStore` seeds from."""
    return client.get("/api/scenarios").json()["authored_overlays"]


def _authored_ids(client: TestClient) -> List[str]:
    return client.get("/api/scenarios").json()["authored_ids"]


def _seed_entry(cfg_path: Path, scenario_id: str) -> Path:
    """Write one solved entry for *cfg_path*, as a real solve would.

    The store location is derived from the config path, so seeding it needs no
    ``app.state`` wiring. Returns the store directory.
    """
    from boulder import scenario_store
    from boulder.runset import resolve_store_dir

    store_dir = resolve_store_dir({}, cfg_path)
    assert store_dir is not None
    scenario_store.write_entry(
        store_dir,
        scenario_id,
        gui_payload={"status": "complete", "times": [], "reactors_series": {}},
        mechanism="gri30.yaml",
        fingerprint=f"fp-{scenario_id}",
        identity=scenario_store.config_identity(cfg_path),
    )
    return store_dir


def test_create_scenario_works_without_a_config_path() -> None:
    """Scenario creation is a pure function now -- no config file is required."""
    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = None
        resp = client.post(
            "/api/scenarios", json={"overlays": {}, "scenario_id": "new1"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["overlays"] == {"new1": {}}


def test_create_scenario_blank(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.post(
            "/api/scenarios", json={"overlays": overlays, "scenario_id": "new1"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["scenario_id"] == "new1"
        assert set(resp.json()["overlays"].keys()) == {"base_case", "new1"}
        # Nothing here ever touches disk -- the pre-existing comment (and
        # everything else in the file) is exactly as it was.
        assert cfg.read_text(encoding="utf-8") == _BASE_YAML
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_clone(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.post(
            "/api/scenarios",
            json={
                "overlays": overlays,
                "scenario_id": "clone1",
                "base_scenario_id": "base_case",
            },
        )
        assert resp.status_code == 200, resp.text
        assert "description:" in resp.json()["yaml"]
        assert "Base Case" in resp.json()["yaml"]
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_with_description(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.post(
            "/api/scenarios",
            json={
                "overlays": overlays,
                "scenario_id": "new1",
                "description": "Case 1 max",
            },
        )
        assert resp.status_code == 200, resp.text
        assert "Case 1 max" in resp.json()["yaml"]
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_clone_description_overrides_inherited(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.post(
            "/api/scenarios",
            json={
                "overlays": overlays,
                "scenario_id": "clone1",
                "base_scenario_id": "base_case",
                "description": "Distinct description",
            },
        )
        assert resp.status_code == 200, resp.text
        yaml_text = resp.json()["yaml"]
        assert "Distinct description" in yaml_text
        assert "Base Case" not in yaml_text
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_duplicate_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.post(
            "/api/scenarios", json={"overlays": overlays, "scenario_id": "base_case"}
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_bad_id_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post(
            "/api/scenarios", json={"overlays": {}, "scenario_id": "bad id!"}
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_reserved_baseline_id_422(tmp_path: Path) -> None:
    """BASELINE is reserved for the synthesized unmodified-base entry.

    A user-authored "scenarios: {BASELINE: ...}" would otherwise collide with
    it in expand_scenarios' run-set.
    """
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post(
            "/api/scenarios", json={"overlays": {}, "scenario_id": "BASELINE"}
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_clone_from_baseline_is_blank(tmp_path: Path) -> None:
    """Cloning "BASELINE" must produce a blank overlay, not an unknown-base error.

    BASELINE is the unmodified base config, not a real overlays-map entry.
    """
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.post(
            "/api/scenarios",
            json={
                "overlays": overlays,
                "scenario_id": "from_baseline",
                "base_scenario_id": "BASELINE",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["yaml"].strip() in ("", "{}")
    finally:
        client.__exit__(None, None, None)


def test_create_scenario_unknown_base_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post(
            "/api/scenarios",
            json={"overlays": {}, "scenario_id": "new1", "base_scenario_id": "nope"},
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_get_scenario_source(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.post(
            "/api/scenarios/base_case/source", json={"overlay": overlays["base_case"]}
        )
        assert resp.status_code == 200
        assert "description" in resp.json()["yaml"]
    finally:
        client.__exit__(None, None, None)


def test_get_scenario_source_renders_whatever_overlay_is_sent(tmp_path: Path) -> None:
    """Stateless: there's no server-side "unknown scenario" to 404 on anymore."""
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post("/api/scenarios/nope/source", json={"overlay": {}})
        assert resp.status_code == 200
        assert resp.json()["yaml"].strip() in ("", "{}")
    finally:
        client.__exit__(None, None, None)


def test_update_scenario(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        new_yaml = (
            "metadata:\n  description: Updated\n"
            "network:\n  - id: feed\n    Reservoir:\n      temperature: 350.0\n"
        )
        resp = client.patch(
            "/api/scenarios/base_case", json={"overlays": overlays, "yaml": new_yaml}
        )
        assert resp.status_code == 200, resp.text
        assert "Updated" in resp.json()["yaml"]
        assert (
            resp.json()["overlays"]["base_case"]["metadata"]["description"] == "Updated"
        )
        # Nothing here ever touches disk.
        assert "Updated" not in cfg.read_text(encoding="utf-8")
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_invalid_yaml_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/base_case",
            json={"overlays": overlays, "yaml": "not: [valid: yaml"},
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_unknown_422(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.patch(
            "/api/scenarios/nope", json={"overlays": {}, "yaml": "a: 1"}
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


# --------------------------------------------------------------------------- #
# PATCH /api/scenarios/{id}/entities/{entity_id} — structured overlay edits.
#
# STONE v2 is authored per-stage (or one flat `network:` list), never as a
# generic `nodes:`/`connections:` + `properties:` shape — that only exists
# internally after normalization. This fixture mirrors the real shape
# (tests/fixtures/stone_v2/valid/02_staged_logical_handoff.yaml): two stages,
# a kind-keyed node/connection, and one kind-less logical connection.
# --------------------------------------------------------------------------- #

_STAGED_YAML = """\
phases:
  gas:
    mechanism: gri30.yaml

stages:
  torch_stage:
    mechanism: gri30.yaml
    solve: advance
    advance_time: 1 ms
  psr_stage:
    mechanism: gri30.yaml
    solve: advance_to_steady_state

torch_stage:
- id: inlet
  Reservoir:
    temperature: 300 K
    composition: CH4:1
- id: torch
  IdealGasReactor:
    volume: 1 L
- id: inlet_to_torch
  MassFlowController:
    mass_flow_rate: 0.1 kg/s
  source: inlet
  target: torch

psr_stage:
- id: psr
  IdealGasReactor:
    volume: 5 L
- id: torch_to_psr
  source: torch
  target: psr

scenarios:
  s_case: {}
"""


def _write_staged_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "staged_config.yaml"
    cfg.write_text(_STAGED_YAML, encoding="utf-8")
    return cfg


def test_update_scenario_entity_creates_overlay_entry(tmp_path: Path) -> None:
    cfg = _write_staged_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/s_case/entities/torch",
            json={"overlays": overlays, "properties": {"volume": 2.0}},
        )
        assert resp.status_code == 200, resp.text
        # Lands under the node's own stage list ("torch_stage"), not "network".
        overlay = resp.json()["overlays"]["s_case"]
        torch_entry = next(n for n in overlay["torch_stage"] if n["id"] == "torch")
        assert torch_entry["IdealGasReactor"]["volume"] == 2.0
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_entity_merges_into_existing_entry(tmp_path: Path) -> None:
    """A second edit adds a key without clobbering the first override."""
    cfg = _write_staged_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp1 = client.patch(
            "/api/scenarios/s_case/entities/torch",
            json={"overlays": overlays, "properties": {"volume": 2.0}},
        )
        overlays2 = resp1.json()["overlays"]
        resp2 = client.patch(
            "/api/scenarios/s_case/entities/inlet_to_torch",
            json={"overlays": overlays2, "properties": {"mass_flow_rate": 0.2}},
        )
        assert resp2.status_code == 200, resp2.text
        overlay = resp2.json()["overlays"]["s_case"]
        torch_entry = next(n for n in overlay["torch_stage"] if n["id"] == "torch")
        assert torch_entry["IdealGasReactor"]["volume"] == 2.0
        mfc_entry = next(
            n for n in overlay["torch_stage"] if n["id"] == "inlet_to_torch"
        )
        assert mfc_entry["MassFlowController"]["mass_flow_rate"] == 0.2
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_entity_kindless_logical_connection(tmp_path: Path) -> None:
    """A logical connection (no type key) gets properties directly on the item."""
    cfg = _write_staged_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/s_case/entities/torch_to_psr",
            json={"overlays": overlays, "properties": {"logical": True}},
        )
        assert resp.status_code == 200, resp.text
        overlay = resp.json()["overlays"]["s_case"]
        entry = next(n for n in overlay["psr_stage"] if n["id"] == "torch_to_psr")
        assert entry["logical"] is True
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_entity_baseline_422(tmp_path: Path) -> None:
    cfg = _write_staged_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/BASELINE/entities/torch",
            json={"overlays": overlays, "properties": {"volume": 2.0}},
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_entity_unknown_scenario_422(tmp_path: Path) -> None:
    cfg = _write_staged_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/nope/entities/torch",
            json={"overlays": overlays, "properties": {"volume": 2.0}},
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_entity_unknown_entity_422(tmp_path: Path) -> None:
    cfg = _write_staged_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/s_case/entities/nope",
            json={"overlays": overlays, "properties": {"volume": 2.0}},
        )
        assert resp.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_update_scenario_entity_empty_properties_is_noop(tmp_path: Path) -> None:
    cfg = _write_staged_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/s_case/entities/torch",
            json={"overlays": overlays, "properties": {}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["yaml"].strip() in ("", "{}")
    finally:
        client.__exit__(None, None, None)


def test_rename_scenario(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.patch(
            "/api/scenarios/base_case/rename",
            json={"overlays": overlays, "new_id": "renamed"},
        )
        assert resp.status_code == 200, resp.text
        assert set(resp.json()["overlays"].keys()) == {"renamed"}
    finally:
        client.__exit__(None, None, None)


def test_delete_scenario(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.request(
            "DELETE", "/api/scenarios/base_case", json={"overlays": overlays}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["overlays"] == {}
    finally:
        client.__exit__(None, None, None)


def test_delete_scenario_purges_cached_group(tmp_path: Path) -> None:
    """Deleting a scenario immediately removes its cached entry too.

    Not left for the next Run Sweep to notice and prune — the Scenario Pane's
    "N cached" count and the store on disk stay in sync with the config the
    moment you click Delete.
    """
    pytest.importorskip("h5py")

    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        from boulder.runset import store_entry_path

        store_dir = _seed_entry(cfg, "base_case")
        assert store_entry_path(store_dir, "base_case").is_file()

        overlays = _authored_overlays(client)
        resp = client.request(
            "DELETE", "/api/scenarios/base_case", json={"overlays": overlays}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cache_purged"] is True
        assert not store_entry_path(store_dir, "base_case").exists()
    finally:
        client.__exit__(None, None, None)


def test_delete_scenario_without_cached_group_reports_false(tmp_path: Path) -> None:
    """`cache_purged` is False when there was nothing cached to clear."""
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        overlays = _authored_overlays(client)
        resp = client.request(
            "DELETE", "/api/scenarios/base_case", json={"overlays": overlays}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cache_purged"] is False
    finally:
        client.__exit__(None, None, None)


def test_delete_scenario_unknown_404(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.request("DELETE", "/api/scenarios/nope", json={"overlays": {}})
        assert resp.status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_clear_scenario_cache_deletes_the_store(tmp_path: Path) -> None:
    """Clearing the cache removes the whole store directory, entries and artifacts.

    A per-file delete would orphan the host-contributor artifacts sitting beside
    the entries.
    """
    pytest.importorskip("h5py")

    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        store_dir = _seed_entry(cfg, "base_case")
        artifacts = store_dir / "artifacts" / "base_case"
        artifacts.mkdir(parents=True)
        (artifacts / "bundle.json").write_text("{}", encoding="utf-8")

        resp = client.post("/api/scenarios/clear-cache")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "cleared": True}
        assert not store_dir.exists()
        assert not artifacts.exists(), "artifacts outlived the cleared store"
        # Scenario definitions are untouched -- this only ever affected the
        # results cache, never the scenario overlays themselves.
        assert _authored_ids(client) == ["BASELINE", "base_case"]
    finally:
        client.__exit__(None, None, None)


def test_clear_scenario_cache_without_a_store_reports_false(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.post("/api/scenarios/clear-cache")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "cleared": False}
    finally:
        client.__exit__(None, None, None)


def test_clear_one_entry_cache_keeps_the_definition(tmp_path: Path) -> None:
    """The per-row eraser drops one entry only; the scenario stays authored."""
    pytest.importorskip("h5py")
    from boulder.scenario_store import store_entry_path

    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        store_dir = _seed_entry(cfg, "base_case")
        _seed_entry(cfg, "other")

        resp = client.post("/api/scenarios/base_case/clear-cache")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "ok": True,
            "scenario_id": "base_case",
            "cleared": True,
        }
        assert not store_entry_path(store_dir, "base_case").exists()
        assert store_entry_path(store_dir, "other").is_file(), "cleared too much"
        assert _authored_ids(client) == ["BASELINE", "base_case"]

        # Nothing left to clear the second time round.
        resp = client.post("/api/scenarios/base_case/clear-cache")
        assert resp.json()["cleared"] is False
    finally:
        client.__exit__(None, None, None)


def test_list_scenarios_includes_authored_ids_without_a_store(tmp_path: Path) -> None:
    """authored_ids/authored_overlays reflect the YAML directly, even with no HDF5 store.

    This is the seed `scenarioStore` uses even before the first sweep.
    """
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        resp = client.get("/api/scenarios")
        assert resp.status_code == 200
        body = resp.json()
        # `available` now means "the Scenario pane is meaningful for this
        # config", i.e. it declares scenarios -- not "results exist yet". Every
        # config has a base entry now, so keying it on store presence would
        # light the pane up for every plain single-reactor config.
        assert body["available"] is True
        assert body["scenarios"] == [], "nothing has been solved yet"
        assert body["authored_ids"] == ["BASELINE", "base_case"]
        assert "base_case" in body["authored_overlays"]
    finally:
        client.__exit__(None, None, None)


def test_list_scenarios_reflects_only_the_startup_snapshot(tmp_path: Path) -> None:
    """Creating/editing a scenario doesn't persist anywhere server-side.

    A later GET still only reflects the config's startup `scenarios:` block,
    not anything created via a previous, independent request. From here on,
    a newly created scenario lives only in the caller's own state (mirrored
    by `scenarioStore.overlays` in the frontend).
    """
    cfg = _write_config(tmp_path)
    client, _app = _client_with_config(cfg)
    try:
        client.post("/api/scenarios", json={"overlays": {}, "scenario_id": "new1"})
        resp = client.get("/api/scenarios")
        assert resp.json()["authored_ids"] == ["BASELINE", "base_case"]
    finally:
        client.__exit__(None, None, None)


def test_list_scenarios_authored_ids_empty_without_a_config_path() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = None
        resp = client.get("/api/scenarios")
        assert resp.status_code == 200
        assert resp.json()["authored_ids"] == []
