"""Tests for boulder.result_cache.

Asserts:
- compute_fingerprint is deterministic and changes when config or mechanism changes.
- save_result / load_result round-trips the GUI payload and config snapshot.
- A CACHE_VERSION mismatch causes load_result to return None (invalidation).
- Missing COMPLETE marker causes load_result to return None (incomplete write guard).
- Pruning removes oldest entries when MAX_CACHE_ENTRIES is exceeded.
- GET /api/simulations/cached returns {"cached": false} when no cache exists.
- CacheContributorPlugin subclasses register and are called during run_contributors.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from boulder.result_cache import (
    CACHE_VERSION,
    CacheContributorPlugin,
    CacheContributorRegistry,
    _entry_dir,
    _prune_cache,
    _source_identity,
    cache_dir_for,
    compute_fingerprint,
    load_result,
    lookup_cached_result,
    resolve_mechanism_for_fingerprint,
    run_contributors,
    save_alias,
    save_result,
)

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


# ---------------------------------------------------------------------------
# save_result / load_result
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path: Path):
        """save_result followed by load_result returns identical payload and snapshot."""
        fingerprint = "a" * 64
        save_result(
            cache_root=tmp_path,
            fingerprint=fingerprint,
            gui_payload=SIMPLE_PAYLOAD,
            config_snapshot=SIMPLE_CONFIG,
            mechanism="gri30.yaml",
        )
        loaded = load_result(tmp_path, fingerprint)

        assert loaded is not None
        assert loaded["fingerprint"] == fingerprint
        assert loaded["gui_payload"]["status"] == "complete"
        assert loaded["config_snapshot"]["phases"]["gas"]["mechanism"] == "gri30.yaml"
        assert isinstance(loaded["artifacts_dir"], Path)

    def test_complete_marker_required(self, tmp_path: Path):
        """load_result returns None when COMPLETE marker is absent."""
        fingerprint = "b" * 64
        entry = _entry_dir(tmp_path, fingerprint)
        entry.mkdir(parents=True)
        (entry / "result.h5").write_bytes(b"")  # content irrelevant: COMPLETE is absent
        (entry / "meta.json").write_text(
            json.dumps({"cache_version": CACHE_VERSION}), encoding="utf-8"
        )
        # No COMPLETE file written
        assert load_result(tmp_path, fingerprint) is None

    def test_version_mismatch_invalidates(self, tmp_path: Path):
        """A stale cache_version in meta.json causes load_result to return None."""
        fingerprint = "c" * 64
        save_result(
            cache_root=tmp_path,
            fingerprint=fingerprint,
            gui_payload=SIMPLE_PAYLOAD,
            config_snapshot=SIMPLE_CONFIG,
        )
        # Overwrite meta.json with mismatched version
        entry = _entry_dir(tmp_path, fingerprint)
        meta_path = entry / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["cache_version"] = CACHE_VERSION + 99
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        assert load_result(tmp_path, fingerprint) is None

    def test_missing_entry_returns_none(self, tmp_path: Path):
        """load_result returns None for a fingerprint that was never saved."""
        assert load_result(tmp_path, "d" * 64) is None

    def test_meta_contains_versions(self, tmp_path: Path):
        """Saved meta.json includes boulder_version and cantera_version keys."""
        fingerprint = "e" * 64
        save_result(
            cache_root=tmp_path,
            fingerprint=fingerprint,
            gui_payload=SIMPLE_PAYLOAD,
            config_snapshot=SIMPLE_CONFIG,
        )
        loaded = load_result(tmp_path, fingerprint)
        assert loaded is not None
        meta = loaded["meta"]
        assert "boulder_version" in meta
        assert "cantera_version" in meta
        assert meta["cache_version"] == CACHE_VERSION

    def test_artifacts_dir_exists(self, tmp_path: Path):
        """The artifacts/ subdirectory exists after save_result."""
        fingerprint = "f" * 64
        save_result(
            cache_root=tmp_path,
            fingerprint=fingerprint,
            gui_payload=SIMPLE_PAYLOAD,
            config_snapshot=SIMPLE_CONFIG,
        )
        loaded = load_result(tmp_path, fingerprint)
        assert loaded is not None
        assert loaded["artifacts_dir"].is_dir()

    def test_numpy_coercion(self, tmp_path: Path):
        """save_result coerces numpy-like scalars to JSON-native types."""
        import numpy as np

        fingerprint = "g" * 64
        payload_with_numpy = {
            **SIMPLE_PAYLOAD,
            "elapsed_time": np.float64(2.5),
            "summary": [{"value": np.int32(42), "label": "T"}],
        }
        save_result(
            cache_root=tmp_path,
            fingerprint=fingerprint,
            gui_payload=payload_with_numpy,
            config_snapshot=SIMPLE_CONFIG,
        )
        loaded = load_result(tmp_path, fingerprint)
        assert loaded is not None
        assert loaded["gui_payload"]["elapsed_time"] == 2.5
        assert loaded["gui_payload"]["summary"][0]["value"] == 42


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


class TestPruning:
    def test_prune_keeps_max_entries(self, tmp_path: Path):
        """Saving more than MAX_CACHE_ENTRIES entries prunes the oldest ones."""
        from boulder.result_cache import MAX_CACHE_ENTRIES

        # Write MAX_CACHE_ENTRIES + 2 entries with distinct fingerprints
        fingerprints = []
        for i in range(MAX_CACHE_ENTRIES + 2):
            fp = f"{i:064x}"
            fingerprints.append(fp)
            save_result(
                cache_root=tmp_path,
                fingerprint=fp,
                gui_payload=SIMPLE_PAYLOAD,
                config_snapshot=SIMPLE_CONFIG,
            )
            time.sleep(0.01)  # ensure mtime ordering

        complete_entries = [
            d for d in tmp_path.iterdir() if d.is_dir() and (d / "COMPLETE").exists()
        ]
        assert len(complete_entries) == MAX_CACHE_ENTRIES

    def test_env_raises_max_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """BOULDER_CACHE_MAX_ENTRIES lifts the cap (batch/sweep runners need it)."""
        from boulder.result_cache import MAX_CACHE_ENTRIES

        n = MAX_CACHE_ENTRIES + 4
        monkeypatch.setenv("BOULDER_CACHE_MAX_ENTRIES", str(n + 10))
        for i in range(n):
            save_result(
                cache_root=tmp_path,
                fingerprint=f"{i:064x}",
                gui_payload=SIMPLE_PAYLOAD,
                config_snapshot=SIMPLE_CONFIG,
            )
        complete_entries = [
            d for d in tmp_path.iterdir() if d.is_dir() and (d / "COMPLETE").exists()
        ]
        # All kept: the raised cap exceeds the number of entries written.
        assert len(complete_entries) == n


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


class TestLookupCachedResult:
    def test_hit_via_alias(self, tmp_path: Path):
        """lookup_cached_result follows post-build alias files."""
        canonical = compute_fingerprint(SIMPLE_CONFIG, mechanism="gri30.yaml")
        post_build = dict(SIMPLE_CONFIG)
        post_build["nodes"] = list(SIMPLE_CONFIG["nodes"]) + [
            {"id": "outlet", "type": "Reservoir", "properties": {}}
        ]
        post_fp = compute_fingerprint(post_build, mechanism="gri30.yaml")
        save_result(
            cache_root=tmp_path,
            fingerprint=canonical,
            gui_payload=SIMPLE_PAYLOAD,
            config_snapshot=post_build,
        )
        save_alias(tmp_path, post_fp, canonical)
        fingerprint, cached = lookup_cached_result(
            tmp_path, post_build, mechanism="gri30.yaml"
        )
        assert cached is not None
        assert fingerprint == post_fp

    def test_snapshot_fallback(self, tmp_path: Path):
        """lookup_cached_result accepts a matching preloaded snapshot."""
        fingerprint = compute_fingerprint(SIMPLE_CONFIG, mechanism="gri30.yaml")
        preloaded = {
            "fingerprint": fingerprint,
            "gui_payload": SIMPLE_PAYLOAD,
            "config_snapshot": SIMPLE_CONFIG,
            "meta": {"cache_version": CACHE_VERSION},
        }
        fp, cached = lookup_cached_result(
            tmp_path,
            SIMPLE_CONFIG,
            mechanism="gri30.yaml",
            preloaded_result=preloaded,
        )
        assert fp == fingerprint
        assert cached is preloaded


class TestAliasPruning:
    def test_orphan_alias_removed_after_entry_pruned(self, tmp_path: Path):
        """_prune_cache deletes alias files whose canonical entry was removed."""
        from boulder.result_cache import MAX_CACHE_ENTRIES

        fingerprints = []
        for i in range(MAX_CACHE_ENTRIES + 2):
            fp = f"{i:064x}"
            fingerprints.append(fp)
            save_result(
                cache_root=tmp_path,
                fingerprint=fp,
                gui_payload=SIMPLE_PAYLOAD,
                config_snapshot=SIMPLE_CONFIG,
            )
            time.sleep(0.01)

        orphan_alias = tmp_path / f"_alias_{'f' * 64}"
        orphan_alias.write_text(fingerprints[0], encoding="utf-8")
        _prune_cache(tmp_path)
        assert not orphan_alias.exists()


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
        """TestClient with a pre-populated cache entry injected after startup.

        We set app.state inside the TestClient context manager (after lifespan
        startup) so that the lifespan reset does not overwrite our value.
        """
        from boulder.config import synthesize_default_group

        fingerprint = "j" * 64
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        # Real cache entries snapshot the config the worker received — i.e.
        # AFTER default-group synthesis — and /check-cache normalizes the
        # submitted config the same way before fingerprinting.
        snapshot = copy.deepcopy(SIMPLE_CONFIG)
        synthesize_default_group(snapshot)
        cache_data = {
            "fingerprint": fingerprint,
            "gui_payload": SIMPLE_PAYLOAD,
            "config_snapshot": snapshot,
            "meta": {"cache_version": CACHE_VERSION, "created_at": time.time()},
            "artifacts_dir": artifacts_dir,
        }
        app = create_app()
        with TestClient(app) as client:
            # Inject after lifespan startup
            app.state.preloaded_result = cache_data
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

    def test_artifact_missing_returns_404(self, client_with_cache: TestClient):
        """GET /api/simulations/cached/artifacts/missing.txt returns 404."""
        resp = client_with_cache.get("/api/simulations/cached/artifacts/missing.txt")
        assert resp.status_code == 404

    def test_artifact_served(self, client_with_cache: TestClient, tmp_path: Path):
        """GET /api/simulations/cached/artifacts/<name> serves existing artifact files."""
        artifacts_dir = tmp_path / "artifacts"
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
        cfg = tmp_path / "case.yaml"
        cfg.write_text("x: 1", encoding="utf-8")
        cast(FastAPI, client_with_cache.app).state.preloaded_config_path = str(cfg)
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
        from boulder.api.routes.simulations import _resolve_run_grid
        from boulder.config import synthesize_default_group

        snapshot = copy.deepcopy(SIMPLE_CONFIG)
        synthesize_default_group(snapshot)
        _resolve_run_grid(snapshot, 5.0, 0.5)

        fingerprint = "k" * 64
        artifacts_dir = tmp_path / "artifacts2"
        artifacts_dir.mkdir()
        app = create_app()
        with TestClient(app) as client:
            app.state.preloaded_result = {
                "fingerprint": fingerprint,
                "gui_payload": SIMPLE_PAYLOAD,
                "config_snapshot": snapshot,
                "meta": {"cache_version": CACHE_VERSION, "created_at": time.time()},
                "artifacts_dir": artifacts_dir,
            }
            cfg = tmp_path / "case2.yaml"
            cfg.write_text("x: 1", encoding="utf-8")
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
        cfg = tmp_path / "case.yaml"
        cfg.write_text("x: 1", encoding="utf-8")
        cast(FastAPI, client_with_cache.app).state.preloaded_config_path = str(cfg)
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
