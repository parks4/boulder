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
from boulder.result_cache import (
    CacheContributorPlugin,
    CacheContributorRegistry,
    _source_identity,
    cache_dir_for,
    compute_fingerprint,
    run_contributors,
)
from boulder.runset import resolve_store_dir
from boulder.sweep_runner import solver_window, with_time_overrides

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: The server's live config (``app.state.preloaded_raw``): what a run expands and
#: the cache check fingerprints.
LIVE_RAW: Dict[str, Any] = {
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "settings": {"solver": {"kind": "advance_to_steady_state"}},
    "network": [
        {
            "id": "r1",
            "IdealGasReactor": {
                "volume": 1.0,
                "initial": {
                    "temperature": 1000,
                    "pressure": 101325,
                    "composition": "N2:1",
                },
            },
        }
    ],
}

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
# solver_window / with_time_overrides
# ---------------------------------------------------------------------------


class TestSolverWindow:
    """``solver_window``: the one time-grid rule, read from the prepared config.

    Regression coverage for a bug where an advance_grid/advance config's real
    settings.solver.grid.{stop,dt} (or advance_time) was ignored in favor of a
    hard-coded default, because the fallback only ever looked at the top-level
    settings.end_time/dt keys. That wrong total_time fed the "Using config
    parameters" log line and progress.total_time (the run itself, driven by
    groups.<stage>.solver, was unaffected).
    """

    def test_advance_grid_stop_dt_used_when_no_nominal_window(self):
        config = {
            "settings": {
                "solver": {
                    "kind": "advance_grid",
                    "grid": {"start": 0.0, "stop": 5e-8, "dt": 1e-11},
                }
            }
        }
        simulation_time, time_step = solver_window(config)
        assert simulation_time == pytest.approx(5e-8)
        assert time_step == pytest.approx(1e-11)

    def test_advance_time_used_for_flat_advance_kind(self):
        config = {"settings": {"solver": {"kind": "advance", "advance_time": 2.5e-6}}}
        simulation_time, time_step = solver_window(config)
        assert simulation_time == pytest.approx(2.5e-6)
        assert time_step == pytest.approx(2.5e-7)  # a tenth of the window

    def test_solver_grid_takes_priority_over_nominal_end_time_dt(self, caplog):
        """The window is what the solve integrates: the grid wins, with a warning."""
        config = {
            "settings": {
                "end_time": 3.0,
                "dt": 0.1,
                "solver": {"kind": "advance_grid", "grid": {"stop": 5e-8, "dt": 1e-11}},
            }
        }
        # Wired to the logger directly: another test's ``--verbose`` run may
        # have switched propagation of ``boulder.*`` off.
        sweep_log = logging.getLogger("boulder.sweep_runner")
        sweep_log.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger="boulder.sweep_runner"):
                simulation_time, time_step = solver_window(config)
        finally:
            sweep_log.removeHandler(caplog.handler)
        assert simulation_time == pytest.approx(5e-8)
        assert time_step == pytest.approx(1e-11)
        assert (
            "settings.end_time (3) and the solver's end (5e-08) differ" in caplog.text
        )

    def test_no_time_at_all_has_no_hidden_default(self):
        assert solver_window({"settings": {}}) == (0.0, 0.0)


class TestWithTimeOverrides:
    """The GUI's time fields are written into ``settings.solver`` of a copy."""

    _GRID = {"kind": "advance_grid", "grid": {"stop": 5e-8, "dt": 1e-11}}

    def test_no_override_returns_the_config_itself(self):
        config = {"settings": {"solver": copy.deepcopy(self._GRID)}}
        assert with_time_overrides(config, None, None) is config

    def test_override_is_written_to_a_copy_and_the_original_is_kept(self):
        config = {"settings": {"solver": copy.deepcopy(self._GRID)}}
        result = with_time_overrides(config, 20.0, 0.5)
        assert result["settings"]["solver"]["grid"]["stop"] == pytest.approx(20.0)
        assert result["settings"]["solver"]["grid"]["dt"] == pytest.approx(0.5)
        assert config["settings"]["solver"]["grid"] == self._GRID["grid"]
        assert solver_window(result) == (20.0, 0.5)

    def test_a_missing_grid_is_synthesised_with_the_default_kind(self):
        result = with_time_overrides({"settings": {}}, 5.0, 0.5)
        assert result["settings"]["solver"] == {
            "kind": "advance_grid",
            "grid": {"stop": 5.0, "dt": 0.5},
        }

    def test_an_explicit_list_grid_is_left_untouched(self):
        solver = {"kind": "advance_grid", "grid": [0.0, 1.0, 2.0]}
        result = with_time_overrides({"settings": {"solver": solver}}, 5.0, 0.5)
        assert result["settings"]["solver"]["grid"] == [0.0, 1.0, 2.0]

    def test_a_non_positive_override_is_refused(self):
        with pytest.raises(ValueError, match="time_step must be > 0"):
            with_time_overrides({"settings": {}}, 5.0, 0.0)


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


class TestConverterMechanismResolver:
    def test_subclass_override_is_applied(self):
        """The fingerprint hashes the converter subclass's resolved mechanism."""
        from boulder.sweep_runner import (
            converter_mechanism_resolver,
            scenario_fingerprint,
        )

        class _RedirectConverter:
            def resolve_mechanism(self, name: str) -> str:
                return "h2o2.yaml"

        fp_reader = scenario_fingerprint(
            SIMPLE_CONFIG,
            normalized=True,
            resolve_mechanism=converter_mechanism_resolver(_RedirectConverter),
        )
        # A bare normalized config also gets the default group synthesised.
        fp_direct = scenario_fingerprint(
            SIMPLE_CONFIG,
            normalized=True,
            mechanism="h2o2.yaml",
            resolve_mechanism=lambda name: name,
        )
        assert fp_reader == fp_direct


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

    Fingerprints through the same preparation ``check-cache`` applies (the live
    config, with any time override written in, then the base entry's key), so a
    seeded entry is one the endpoint can actually match.
    """
    from boulder.sweep_runner import prepare_entry

    mechanism = "gri30.yaml"
    raw = with_time_overrides(copy.deepcopy(config), simulation_time, time_step)
    fingerprint = prepare_entry(raw, "BASELINE")[2]
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
        fingerprint = _seed_store(cfg, LIVE_RAW, SIMPLE_PAYLOAD)

        app = create_app()
        with TestClient(app) as client:
            # Inject after lifespan startup, exactly as the startup check does.
            app.state.preloaded_config_path = str(cfg)
            app.state.preloaded_raw = copy.deepcopy(LIVE_RAW)
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
        fingerprint = _seed_store(cfg, LIVE_RAW, poisoned_payload)

        app = create_app()
        with TestClient(app) as client:
            app.state.preloaded_config_path = str(cfg)
            app.state.preloaded_raw = copy.deepcopy(LIVE_RAW)
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

            resp2 = client.post("/api/simulations/check-cache", json={})
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
            resp = client_with_cache.post("/api/simulations/check-cache", json={})
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
        _seed_store(cfg, LIVE_RAW, SIMPLE_PAYLOAD, simulation_time=5.0, time_step=0.5)

        app = create_app()
        with TestClient(app) as client:
            app.state.preloaded_config_path = str(cfg)
            app.state.preloaded_raw = copy.deepcopy(LIVE_RAW)

            hit = client.post(
                "/api/simulations/check-cache",
                json={
                    "simulation_time": 5.0,
                    "time_step": 0.5,
                },
            )
            assert hit.status_code == 200
            assert hit.json()["cached"] is True

            miss = client.post(
                "/api/simulations/check-cache",
                json={
                    "simulation_time": 7.0,
                    "time_step": 0.5,
                },
            )
            assert miss.status_code == 200
            assert miss.json()["cached"] is False

    def test_check_cache_logs_miss(self, client_with_cache: TestClient, tmp_path: Path):
        """POST /check-cache announces a MISS when the live config differs."""
        edited = copy.deepcopy(LIVE_RAW)
        edited["network"][0]["IdealGasReactor"]["initial"]["temperature"] = 2000
        cast(FastAPI, client_with_cache.app).state.preloaded_raw = edited
        pkg = logging.getLogger("boulder")
        handler, messages = self._capture_boulder_log()
        pkg.addHandler(handler)
        try:
            resp = client_with_cache.post("/api/simulations/check-cache", json={})
        finally:
            pkg.removeHandler(handler)
        assert resp.status_code == 200
        assert resp.json()["cached"] is False
        assert any("Cache MISS" in m for m in messages), messages
