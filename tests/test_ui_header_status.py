"""Header status: the server resolves the chip at ``GET /api/ui/header-status``.

Asserts, on a neutral ``gri30.yaml`` network (``feed`` -> ``reactor`` -> ``outlet``):
- with no provider the status is null, and ``/api/ui/header-links`` is unchanged;
- after a single run the provider gets the resolved base id, the session config and
  both the primary and the alternate fingerprint of the stored entry;
- a scenario with no stored result gets ``fingerprints == ()``;
- an unknown id is a 404;
- a bad href, a bad tone or a provider exception is a 500 carrying the detail;
- a provider returning ``None`` gives null; a good answer is normalised.
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
from boulder.cantera_converter import BoulderPlugins  # noqa: E402
from boulder.config import normalize_config  # noqa: E402
from boulder.runset import resolve_store_dir  # noqa: E402
from boulder.simulation_worker import SimulationWorker  # noqa: E402

_RES = {"temperature": 300, "pressure": 101325, "composition": "CH4:1"}
_RAW: Dict[str, Any] = {
    "metadata": {},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "network": [
        {"id": "feed", "Reservoir": _RES},
        {"id": "reactor", "IdealGasReactor": {"volume": 1.0e-3}},
        {"id": "outlet", "Reservoir": _RES},
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
    "scenarios": {
        "hot": {"network": [{"id": "feed", "Reservoir": {"temperature": 900}}]}
    },
}


class _StubConverter:
    mechanism = "gri30.yaml"

    def __init__(self, config_path: Path) -> None:
        self._download_config_path = str(config_path)

        class _Plugins:
            cache_contributors = ()

        self.plugins = _Plugins()

    def resolve_mechanism(self, name: str) -> str:
        return name


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    path = tmp_path / "model.yaml"
    path.write_text("metadata: {}\n", encoding="utf-8")
    return path


def _store_single_run(cfg: Path) -> None:
    """Persist the base run the way the worker does, with a distinct alt fingerprint."""
    config = normalize_config(copy.deepcopy(_RAW))
    pre_build = copy.deepcopy(config)
    config["metadata"] = {"post_build": True}  # the post-build config differs
    worker = SimulationWorker()
    with patch(
        "boulder.simulation_result.make_simulation_result", return_value=object()
    ):
        worker._persist_to_cache(
            _StubConverter(cfg),
            config,
            {"is_complete": True},
            {},
            {},
            "# code",
            pre_build_config=pre_build,
        )


def _get(cfg, provider, url="/api/ui/header-status"):
    plugins = BoulderPlugins(header_status=provider)
    app = create_app()
    with patch("boulder.cantera_converter.get_plugins", lambda: plugins):
        with TestClient(app) as client:
            app.state.preloaded_config_path = str(cfg)
            app.state.preloaded_raw = copy.deepcopy(_RAW)
            return client.get(url)


def test_no_provider_is_null(cfg):
    assert _get(cfg, None).json() == {"status": None}


def test_header_links_has_no_statuses(cfg):
    plugins = BoulderPlugins()
    app = create_app()
    with patch("boulder.cantera_converter.get_plugins", lambda: plugins):
        with TestClient(app) as client:
            assert client.get("/api/ui/header-links").json() == {"links": []}


def test_provider_gets_base_id_and_all_fingerprints(cfg):
    _store_single_run(cfg)
    seen = []

    def provider(ctx):
        seen.append(ctx)
        return {"text": "recorded", "tone": "ok", "href": "/runs/1"}

    resp = _get(cfg, provider)
    assert resp.status_code == 200
    assert resp.json() == {
        "status": {
            "text": "recorded",
            "tone": "ok",
            "href": "/runs/1",
            "tooltip": None,
            "new_tab": False,
        }
    }
    ctx = seen[0]
    attrs = store.list_entries(resolve_store_dir({}, cfg), store.config_identity(cfg))[
        0
    ]
    assert ctx.scenario_id == "BASELINE"
    assert len(ctx.fingerprints) == 2
    assert ctx.fingerprints == store.entry_fingerprints(attrs)
    assert ctx.config["network"][0]["id"] == "feed"


def test_scenario_without_result_has_no_fingerprints(cfg):
    _store_single_run(cfg)
    seen = []

    def provider(ctx):
        seen.append(ctx)

    _get(cfg, provider, "/api/ui/header-status?scenario_id=hot")
    assert seen[0].scenario_id == "hot"
    assert seen[0].fingerprints == ()
    assert seen[0].config["network"][0]["Reservoir"]["temperature"] == 900


def test_unknown_id_is_404(cfg):
    resp = _get(cfg, lambda ctx: None, "/api/ui/header-status?scenario_id=nope")
    assert resp.status_code == 404


def test_provider_none_is_null(cfg):
    assert _get(cfg, lambda ctx: None).json() == {"status": None}


def _boom(ctx):
    raise RuntimeError("index down")


@pytest.mark.parametrize(
    "provider, detail",
    [
        (
            lambda ctx: {"text": "x", "tone": "ok", "href": "javascript:alert(1)"},
            "href",
        ),
        (lambda ctx: {"text": "x", "tone": "purple"}, "tone"),
        (_boom, "index down"),
    ],
)
def test_bad_provider_is_500_with_detail(cfg, provider, detail):
    resp = _get(cfg, provider)
    assert resp.status_code == 500
    assert detail in resp.json()["detail"]
