"""Tests for boulder.result_cache -- now identity only, no storage.

The module used to own a second, content-addressed result store (save/load,
aliases, LRU pruning). :mod:`boulder.scenario_store` is the single store now, so
what remains here is the *identity* layer everything fingerprints through, plus
the contributor registry:

- compute_fingerprint is deterministic and changes when config or mechanism changes.
- cache_dir_for picks the cache root (sidecar, or $BOULDER_CACHE_DIR).
- _source_identity busts the fingerprint on a dirty worktree.
- CacheContributorPlugin subclasses register and are called during run_contributors.

The cache-hit endpoints are covered here too, seeded through the store -- the
only source of truth -- rather than by injecting ``app.state.preloaded_result``,
which would let these pass while the real endpoint missed.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, Optional, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from boulder import scenario_store
from boulder.api.routes.simulations import _resolve_run_grid
from boulder.result_cache import (
    CacheContributorPlugin,
    CacheContributorRegistry,
    _source_identity,
    cache_dir_for,
    compute_fingerprint,
    resolve_mechanism_for_fingerprint,
    run_contributors,
)
from boulder.runset import resolve_store_dir

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestComputeFingerprint:
    def test_deterministic(self):
        """compute_fingerprint returns the same digest for identical inputs."""
        fp1 = compute_fingerprint(SIMPLE_CONFIG, mechanism="gri30.yaml")
        fp2 = compute_fingerprint(SIMPLE_CONFIG, mechanism="gri30.yaml")
        assert fp1 == fp2

    def test_changes_with_config(self):
        """Different configs produce different fingerprints."""
        cfg2 = dict(SIMPLE_CONFIG)
        cfg2["nodes"] = [
            {"id": "r2", "type": "IdealGasReactor", "properties": {"T": 2000}}
        ]
        fp1 = compute_fingerprint(SIMPLE_CONFIG)
        fp2 = compute_fingerprint(cfg2)
        assert fp1 != fp2

    def test_changes_with_mechanism(self):
        """Changing the mechanism changes the fingerprint."""
        fp1 = compute_fingerprint(SIMPLE_CONFIG, mechanism="gri30.yaml")
        fp2 = compute_fingerprint(SIMPLE_CONFIG, mechanism="h2o2.yaml")
        assert fp1 != fp2

    def test_hex_string(self):
        """Fingerprint is a 64-character hex string."""
        fp = compute_fingerprint(SIMPLE_CONFIG)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_extra_included_in_hash(self):
        """Extra dict is included in hash, changing the result."""
        fp1 = compute_fingerprint(SIMPLE_CONFIG)
        fp2 = compute_fingerprint(SIMPLE_CONFIG, extra={"simulation_time": 10.0})
        assert fp1 != fp2


# ---------------------------------------------------------------------------
# _resolve_run_grid
# ---------------------------------------------------------------------------


class TestResolveRunGrid:
    """_resolve_run_grid's settings-derived fallback (no body override).

    Regression coverage for a bug where an advance_grid/advance config's
    real settings.solver.grid.{stop,dt} (or advance_time) was ignored in
    favor of a hard-coded 10.0/1.0 default, because the fallback only ever
    looked at the legacy top-level settings.end_time/max_time/dt/time_step
    keys. That wrong total_time/time_step fed the "Using config parameters"
    log line and progress.total_time (the run itself, driven by
    groups.<stage>.solver, was unaffected).
    """

    def test_advance_grid_stop_dt_used_when_no_legacy_keys_or_override(self):
        config = {
            "settings": {
                "solver": {
                    "kind": "advance_grid",
                    "grid": {"start": 0.0, "stop": 5e-8, "dt": 1e-11},
                }
            }
        }
        simulation_time, time_step = _resolve_run_grid(config, None, None)
        assert simulation_time == pytest.approx(5e-8)
        assert time_step == pytest.approx(1e-11)
        # No override was passed, so the grid must be left untouched.
        assert config["settings"]["solver"]["grid"] == {
            "start": 0.0,
            "stop": 5e-8,
            "dt": 1e-11,
        }

    def test_advance_time_used_for_flat_advance_kind(self):
        config = {"settings": {"solver": {"kind": "advance", "advance_time": 2.5e-6}}}
        simulation_time, time_step = _resolve_run_grid(config, None, None)
        assert simulation_time == pytest.approx(2.5e-6)
        assert time_step == pytest.approx(1.0)  # no dt concept for "advance"

    def test_legacy_end_time_dt_still_take_priority_over_grid(self):
        config = {
            "settings": {
                "end_time": 3.0,
                "dt": 0.1,
                "solver": {"kind": "advance_grid", "grid": {"stop": 5e-8, "dt": 1e-11}},
            }
        }
        simulation_time, time_step = _resolve_run_grid(config, None, None)
        assert simulation_time == pytest.approx(3.0)
        assert time_step == pytest.approx(0.1)

    def test_body_override_still_takes_priority_over_grid(self):
        config = {
            "settings": {
                "solver": {"kind": "advance_grid", "grid": {"stop": 5e-8, "dt": 1e-11}}
            }
        }
        simulation_time, time_step = _resolve_run_grid(config, 20.0, 0.5)
        assert simulation_time == pytest.approx(20.0)
        assert time_step == pytest.approx(0.5)
        # An explicit override IS authoritative and does get written back.
        assert config["settings"]["solver"]["grid"]["stop"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# cache_dir_for
# ---------------------------------------------------------------------------


class TestCacheDirFor:
    def test_sidecar_from_path(self, tmp_path: Path):
        """cache_dir_for returns .boulder-cache next to the YAML when no override."""
        yaml_path = tmp_path / "model.yaml"
        yaml_path.touch()
        result = cache_dir_for(str(yaml_path))
        assert result == yaml_path.parent / ".boulder-cache"

    def test_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """BOULDER_CACHE_DIR env var overrides the sidecar location."""
        override = tmp_path / "custom_cache"
        monkeypatch.setenv("BOULDER_CACHE_DIR", str(override))
        result = cache_dir_for("/some/path/model.yaml")
        assert result == override

    def test_none_without_path_or_env(self, monkeypatch: pytest.MonkeyPatch):
        """Returns None when no config path and no env override."""
        monkeypatch.delenv("BOULDER_CACHE_DIR", raising=False)
        result = cache_dir_for(None)
        assert result is None


class TestSourceIdentity:
    def test_ignore_code_env_uses_package_version(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """BOULDER_CACHE_IGNORE_CODE=1 restores version-only identity."""
        monkeypatch.setenv("BOULDER_CACHE_IGNORE_CODE", "1")
        identity = _source_identity("boulder")
        assert identity.count(".") >= 2 or identity == "unknown"

    def test_dirty_worktree_changes_fingerprint(self, monkeypatch: pytest.MonkeyPatch):
        """Uncommitted changes produce a different fingerprint than a clean tree."""
        monkeypatch.delenv("BOULDER_CACHE_IGNORE_CODE", raising=False)

        def fake_source(package: str) -> str:
            if package == "boulder":
                return "git:abc123"
            return "unknown"

        def fake_dirty(package: str) -> str:
            if package == "boulder":
                return "git:abc123+dirty:deadbeef1234"
            return "unknown"

        monkeypatch.setattr("boulder.result_cache._source_identity", fake_source)
        fp_clean = compute_fingerprint(SIMPLE_CONFIG)
        monkeypatch.setattr("boulder.result_cache._source_identity", fake_dirty)
        fp_dirty = compute_fingerprint(SIMPLE_CONFIG)
        assert fp_clean != fp_dirty


class TestResolveMechanismForFingerprint:
    def test_subclass_override_is_applied(self):
        """resolve_mechanism_for_fingerprint honours converter subclass overrides."""

        class _RedirectConverter:
            def resolve_mechanism(self, name: str) -> str:
                return "/custom/mech.yaml"

        resolved = resolve_mechanism_for_fingerprint(
            SIMPLE_CONFIG,
            converter_class=_RedirectConverter,
        )
        assert resolved == "/custom/mech.yaml"

    def test_reader_writer_use_same_resolved_mechanism(self):
        """Fingerprint with resolved mechanism matches worker-style hashing."""

        class _RedirectConverter:
            def resolve_mechanism(self, name: str) -> str:
                return "h2o2.yaml"

        mechanism = resolve_mechanism_for_fingerprint(
            SIMPLE_CONFIG,
            converter_class=_RedirectConverter,
        )
        fp_reader = compute_fingerprint(SIMPLE_CONFIG, mechanism=mechanism)
        fp_writer = compute_fingerprint(SIMPLE_CONFIG, mechanism="h2o2.yaml")
        assert fp_reader == fp_writer


# ---------------------------------------------------------------------------
# CacheContributorPlugin
# ---------------------------------------------------------------------------


class _DummyContributor(CacheContributorPlugin):
    """Test contributor that writes a sentinel file."""

    @property
    def contributor_id(self) -> str:
        return "test_dummy"

    def contribute(
        self,
        config: Dict[str, Any],
        converter: Any,
        simulation_result: Any,
        fingerprint: str,
        artifacts_dir: Path,
    ) -> None:
        (artifacts_dir / "sentinel.txt").write_text(fingerprint[:8], encoding="utf-8")


class TestCacheContributorPlugin:
    def test_register_and_no_duplicate(self):
        """Registering the same contributor_id twice is a no-op."""
        registry = CacheContributorRegistry()
        c = _DummyContributor()
        registry.register(c)
        registry.register(c)
        assert len(registry.contributors) == 1

    def test_run_contributors_calls_contribute(self, tmp_path: Path):
        """run_contributors invokes each registered contributor."""
        fingerprint = "h" * 64
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        contributor = _DummyContributor()
        run_contributors(
            contributors=[contributor],
            config=SIMPLE_CONFIG,
            converter=MagicMock(),
            simulation_result=MagicMock(),
            fingerprint=fingerprint,
            artifacts_dir=artifacts_dir,
        )

        sentinel = artifacts_dir / "sentinel.txt"
        assert sentinel.is_file()
        assert sentinel.read_text() == fingerprint[:8]

    def test_run_contributors_swallows_errors(self, tmp_path: Path):
        """run_contributors does not raise when a contributor fails."""

        class _FailingContributor(CacheContributorPlugin):
            @property
            def contributor_id(self) -> str:
                return "test_failing"

            def contribute(
                self, config, converter, simulation_result, fingerprint, artifacts_dir
            ):
                raise RuntimeError("intentional failure")

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        # Must not raise even though the contributor throws
        run_contributors(
            contributors=[_FailingContributor()],
            config=SIMPLE_CONFIG,
            converter=MagicMock(),
            simulation_result=MagicMock(),
            fingerprint="i" * 64,
            artifacts_dir=artifacts_dir,
        )
        # If we reach here, the error was swallowed as required.


# ---------------------------------------------------------------------------
# API: GET /api/simulations/cached
# ---------------------------------------------------------------------------


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402


def _seed_store(
    cfg: Path,
    config: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    simulation_time: Optional[float] = None,
    time_step: Optional[float] = None,
) -> str:
    """Solve-and-store *config* for *cfg*, the way a real run leaves it behind.

    Fingerprints through the same normalisation ``check-cache`` applies, so a
    seeded entry is one the endpoint can actually match.
    """
    from boulder.api.routes.simulations import normalize_config_for_fingerprint

    normalized = normalize_config_for_fingerprint(config, simulation_time, time_step)
    mechanism = resolve_mechanism_for_fingerprint(normalized)
    fingerprint = compute_fingerprint(normalized, mechanism=mechanism)
    store_dir = resolve_store_dir({}, str(cfg))
    assert store_dir is not None
    scenario_store.write_entry(
        store_dir,
        "BASE",
        gui_payload=payload,
        mechanism=mechanism,
        fingerprint=fingerprint,
        identity=scenario_store.config_identity(str(cfg)),
    )
    return fingerprint


class TestCachedEndpoint:
    @pytest.fixture
    def client_no_cache(self):
        """TestClient with no preloaded cache.

        The lifespan initialises preloaded_result=None when no BOULDER_CONFIG_PATH
        is set, so the /cached endpoint returns {cached: false}.
        """
        app = create_app()
        with TestClient(app) as client:
            yield client

    @pytest.fixture
    def client_with_cache(self, tmp_path: Path):
        """TestClient whose config already has a solved entry in the store.

        Seeded through the store rather than by injecting ``preloaded_result``
        directly, because that is now the only source of truth: ``check-cache``
        reads the store, so a hand-injected app-state entry would make these
        tests pass while the real endpoint missed.
        """
        cfg = tmp_path / "model.yaml"
        cfg.write_text("x: 1", encoding="utf-8")
        fingerprint = _seed_store(cfg, SIMPLE_CONFIG, SIMPLE_PAYLOAD)

        app = create_app()
        with TestClient(app) as client:
            # Inject after lifespan startup, exactly as the startup check does.
            app.state.preloaded_config_path = str(cfg)
            app.state.preloaded_result = scenario_store.load_matching(
                resolve_store_dir({}, str(cfg)),
                fingerprint,
                scenario_store.config_identity(str(cfg)),
            )
            app.state.preloaded_fingerprint = fingerprint
            yield client

    def test_no_cache_returns_false(self, client_no_cache: TestClient):
        """GET /api/simulations/cached returns {cached: false} when no cache exists."""
        resp = client_no_cache.get("/api/simulations/cached")
        assert resp.status_code == 200
        assert resp.json()["cached"] is False

    def test_cache_present_returns_result(self, client_with_cache: TestClient):
        """GET /api/simulations/cached returns the payload when cache is loaded."""
        resp = client_with_cache.get("/api/simulations/cached")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is True
        assert data["result"]["status"] == "complete"
        assert "fingerprint" in data
        assert "meta" in data

    def test_cached_endpoint_sanitizes_nan_in_payload(self, tmp_path: Path):
        """GET /cached and POST /check-cache must not resurrect a cached NaN.

        Regression: gui_payload is written to disk unsanitized (a NaN in a
        derived reactor-report field survives a save/load round-trip just
        fine on the Python side), so these two cache-hit endpoints carried
        the exact same silent-hang bug as the live-run SSE stream — a NaN
        reaching the browser as the invalid-JSON bare token `NaN` instead of
        `null`. Both must run their response through the same sanitizer.
        """
        poisoned_payload = copy.deepcopy(SIMPLE_PAYLOAD)
        poisoned_payload["reactors_series"]["r1"]["k"] = [float("nan")]

        cfg = tmp_path / "case.yaml"
        cfg.write_text("x: 1", encoding="utf-8")
        fingerprint = _seed_store(cfg, SIMPLE_CONFIG, poisoned_payload)

        app = create_app()
        with TestClient(app) as client:
            app.state.preloaded_config_path = str(cfg)
            app.state.preloaded_result = scenario_store.load_matching(
                resolve_store_dir({}, str(cfg)),
                fingerprint,
                scenario_store.config_identity(str(cfg)),
            )
            app.state.preloaded_fingerprint = fingerprint

            resp = client.get("/api/simulations/cached")
            assert resp.status_code == 200
            body = resp.text
            assert "NaN" not in body
            assert resp.json()["result"]["reactors_series"]["r1"]["k"] == [None]

            resp2 = client.post(
                "/api/simulations/check-cache", json={"config": SIMPLE_CONFIG}
            )
        assert resp2.status_code == 200
        assert "NaN" not in resp2.text
        assert resp2.json()["result"]["reactors_series"]["r1"]["k"] == [None]

    def test_artifact_missing_returns_404(self, client_with_cache: TestClient):
        """GET /api/simulations/cached/artifacts/missing.txt returns 404."""
        resp = client_with_cache.get("/api/simulations/cached/artifacts/missing.txt")
        assert resp.status_code == 404

    def test_artifact_served(self, client_with_cache: TestClient):
        """GET /api/simulations/cached/artifacts/<name> serves existing artifact files."""
        state = cast(FastAPI, client_with_cache.app).state
        artifacts_dir = Path(state.preloaded_result["artifacts_dir"])
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_file = artifacts_dir / "test.txt"
        test_file.write_text("hello", encoding="utf-8")
        resp = client_with_cache.get("/api/simulations/cached/artifacts/test.txt")
        assert resp.status_code == 200
        assert b"hello" in resp.content

    @staticmethod
    def _capture_boulder_log() -> "tuple[logging.Handler, list[str]]":
        """Return a handler for the ``boulder`` logger (propagate=False; caplog is blind)."""
        messages: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                messages.append(record.getMessage())

        handler = _Capture(level=logging.INFO)
        return handler, messages

    def test_check_cache_logs_hit(self, client_with_cache: TestClient, tmp_path: Path):
        """POST /check-cache announces a HIT clearly (the re-run cache message)."""
        pkg = logging.getLogger("boulder")
        handler, messages = self._capture_boulder_log()
        pkg.addHandler(handler)
        try:
            resp = client_with_cache.post(
                "/api/simulations/check-cache", json={"config": SIMPLE_CONFIG}
            )
        finally:
            pkg.removeHandler(handler)
        assert resp.status_code == 200
        assert resp.json()["cached"] is True
        assert any("Cache HIT" in m for m in messages), messages

    def test_check_cache_matches_transient_overrides(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Transient re-runs hit: the check injects time/step like a run would.

        A worker that ran with explicit ``simulation_time``/``time_step``
        saved a snapshot whose ``settings.solver.grid`` carries them; a
        /check-cache call with the same overrides must produce the same
        fingerprint (and a different ``simulation_time`` must not).
        """
        cfg = tmp_path / "case2.yaml"
        cfg.write_text("x: 1", encoding="utf-8")
        # Stored as a run with these overrides applied -- the grid they imply
        # is part of what gets fingerprinted.
        _seed_store(
            cfg, SIMPLE_CONFIG, SIMPLE_PAYLOAD, simulation_time=5.0, time_step=0.5
        )

        app = create_app()
        with TestClient(app) as client:
            app.state.preloaded_config_path = str(cfg)

            hit = client.post(
                "/api/simulations/check-cache",
                json={
                    "config": SIMPLE_CONFIG,
                    "simulation_time": 5.0,
                    "time_step": 0.5,
                },
            )
            assert hit.status_code == 200
            assert hit.json()["cached"] is True

            miss = client.post(
                "/api/simulations/check-cache",
                json={
                    "config": SIMPLE_CONFIG,
                    "simulation_time": 7.0,
                    "time_step": 0.5,
                },
            )
            assert miss.status_code == 200
            assert miss.json()["cached"] is False

    def test_check_cache_logs_miss(self, client_with_cache: TestClient, tmp_path: Path):
        """POST /check-cache announces a MISS when the config differs."""
        other = {
            **SIMPLE_CONFIG,
            "nodes": [
                {"id": "r1", "type": "IdealGasReactor", "properties": {"T": 2000}}
            ],
        }
        pkg = logging.getLogger("boulder")
        handler, messages = self._capture_boulder_log()
        pkg.addHandler(handler)
        try:
            resp = client_with_cache.post(
                "/api/simulations/check-cache", json={"config": other}
            )
        finally:
            pkg.removeHandler(handler)
        assert resp.status_code == 200
        assert resp.json()["cached"] is False
        assert any("Cache MISS" in m for m in messages), messages
