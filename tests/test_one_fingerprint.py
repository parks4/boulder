"""One cache key: the single run, the cache check and a sweep must agree.

``scenario_fingerprint`` is the only implementation of the cache key. The
single-run worker and the cache-check route used to build their own (different
mechanism default, own normalisation, swallowed resolver errors), so a result
stored by a single run was never a hit for a sweep of the same YAML.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

pytest.importorskip("h5py")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder import scenario_store as store  # noqa: E402
from boulder.api.main import create_app  # noqa: E402
from boulder.config import normalize_config  # noqa: E402
from boulder.runset import resolve_store_dir  # noqa: E402
from boulder.simulation_worker import SimulationWorker  # noqa: E402
from boulder.sweep_runner import (  # noqa: E402
    converter_mechanism_resolver,
    prepare_scenario,
    scenario_fingerprint,
)

_NETWORK: Dict[str, Any] = {
    "metadata": {},
    "network": [
        {
            "id": "feed",
            "Reservoir": {
                "temperature": 300,
                "pressure": 101325,
                "composition": "CH4:1",
            },
        },
        {"id": "reactor", "IdealGasReactor": {"volume": 1.0e-3}},
        {
            "id": "outlet",
            "Reservoir": {
                "temperature": 300,
                "pressure": 101325,
                "composition": "CH4:1",
            },
        },
        {
            "id": "in",
            "MassFlowController": {"mass_flow_rate": 0.001},
            "source": "feed",
            "target": "reactor",
        },
        {
            "id": "out",
            "Valve": {"valve_coeff": 1.0},
            "source": "reactor",
            "target": "outlet",
        },
    ],
}


def _raw(mechanism: str | None) -> Dict[str, Any]:
    raw = copy.deepcopy(_NETWORK)
    if mechanism:
        raw["phases"] = {"gas": {"mechanism": mechanism}}
    return raw


class _StubConverter:
    """What `_persist_to_cache` reads off the converter; no Cantera."""

    def __init__(self, config_path: Path, mechanism: str | None) -> None:
        self.mechanism = mechanism
        self._download_config_path = str(config_path)

        class _Plugins:
            cache_contributors = ()

        self.plugins = _Plugins()

    def resolve_mechanism(self, name: str) -> str:
        return name


def _single_run_key(raw: Dict[str, Any], cfg: Path, mechanism: str | None) -> str:
    """Persist ``raw`` the way the worker does after a run; return its stored key."""
    worker = SimulationWorker()
    # The GUI holds (and posts back) the normalized config.
    config = normalize_config(copy.deepcopy(raw))
    with patch(
        "boulder.simulation_result.make_simulation_result", return_value=object()
    ):
        worker._persist_to_cache(
            _StubConverter(cfg, mechanism),
            config,
            {"is_complete": True},
            {},
            {},
            "# code",
            pre_build_config=copy.deepcopy(config),
        )
    store_dir = resolve_store_dir({}, cfg)
    return next(
        iter(store.fingerprints(store_dir, store.config_identity(cfg)).values())
    )


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    path = tmp_path / "model.yaml"
    path.write_text("metadata: {}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("mechanism", ["gri30.yaml", None])
def test_single_run_key_equals_sweep_key(cfg: Path, mechanism: str | None) -> None:
    """The worker stores the key `scenario_fingerprint` gives.

    With or without an explicit mechanism, so a sweep of the same scenario
    finds it current.
    """
    raw = _raw(mechanism)
    # The converter a run builds always carries a mechanism (route default).
    stored = _single_run_key(raw, cfg, mechanism or "gri30.yaml")

    # Same resolver on both sides: a host plugin may remap mechanism names.
    resolve = converter_mechanism_resolver(None)
    assert stored == scenario_fingerprint(raw, resolve_mechanism=resolve)
    # What the sweep loop compares against the store (`cached_fps.get(sid)`).
    assert stored == prepare_scenario(raw, resolve)[2]
    assert (
        stored
        in store.fingerprints(
            resolve_store_dir({}, cfg), store.config_identity(cfg)
        ).values()
    )


@pytest.mark.parametrize("mechanism", ["gri30.yaml", None])
def test_check_cache_route_hits_a_stored_single_run(
    cfg: Path, mechanism: str | None
) -> None:
    """POST /check-cache fingerprints like the worker: a stored run is a hit."""
    raw = _raw(mechanism)
    _single_run_key(raw, cfg, mechanism or "gri30.yaml")

    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = str(cfg)
        app.state.preloaded_raw = {}
        resp = client.post(
            "/api/simulations/check-cache",
            json={"config": normalize_config(copy.deepcopy(raw))},
        )
    assert resp.status_code == 200
    assert resp.json()["cached"] is True


@pytest.mark.parametrize("mechanism", ["gri30.yaml", None])
def test_single_run_then_sweep_is_a_cache_hit(
    cfg: Path, mechanism: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stored single run is skipped, not re-solved, by a sweep of the same YAML."""
    import yaml

    from boulder import sweep_runner

    raw = _raw(mechanism)
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")
    _single_run_key(raw, cfg, mechanism or "gri30.yaml")

    with patch.object(
        sweep_runner, "solve_scenario", side_effect=AssertionError("re-solved")
    ):
        sweep_runner.run(cfg, resolve_mechanism=converter_mechanism_resolver(None))

    assert "cached, skipped" in capsys.readouterr().out


def test_resolver_errors_raise() -> None:
    """A failing mechanism resolver is an error, never a silently raw name."""

    def boom(name: str) -> str:
        raise FileNotFoundError(name)

    with pytest.raises(FileNotFoundError):
        scenario_fingerprint(_raw("gri30.yaml"), resolve_mechanism=boom)


def test_cache_check_resolver_error_is_not_swallowed(cfg: Path) -> None:
    """The route must not hash the raw name when the converter's resolver fails."""

    class _Broken:
        def resolve_mechanism(self, name: str) -> str:
            raise FileNotFoundError(name)

    app = create_app()
    app.state.converter_class = _Broken
    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.converter_class = _Broken
        app.state.preloaded_config_path = str(cfg)
        app.state.preloaded_raw = {}
        with pytest.raises(FileNotFoundError):
            client.post(
                "/api/simulations/check-cache",
                json={"config": normalize_config(_raw("gri30.yaml"))},
            )
