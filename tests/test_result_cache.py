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

import json
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from boulder.result_cache import (
    CACHE_VERSION,
    CacheContributorPlugin,
    CacheContributorRegistry,
    _entry_dir,
    cache_dir_for,
    compute_fingerprint,
    load_result,
    run_contributors,
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
        cfg2["nodes"] = [{"id": "r2", "type": "IdealGasReactor", "properties": {"T": 2000}}]
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
        (entry / "result.json").write_text("{}", encoding="utf-8")
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
            d
            for d in tmp_path.iterdir()
            if d.is_dir() and (d / "COMPLETE").exists()
        ]
        assert len(complete_entries) == MAX_CACHE_ENTRIES


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

            def contribute(self, config, converter, simulation_result, fingerprint, artifacts_dir):
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
        fingerprint = "j" * 64
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        cache_data = {
            "fingerprint": fingerprint,
            "gui_payload": SIMPLE_PAYLOAD,
            "config_snapshot": SIMPLE_CONFIG,
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

    def test_artifact_served(self, client_with_cache: TestClient):
        """GET /api/simulations/cached/artifacts/<name> serves existing artifact files."""
        artifacts_dir = client_with_cache.app.state.preloaded_result["artifacts_dir"]
        test_file = artifacts_dir / "test.txt"
        test_file.write_text("hello", encoding="utf-8")
        resp = client_with_cache.get("/api/simulations/cached/artifacts/test.txt")
        assert resp.status_code == 200
        assert b"hello" in resp.content
