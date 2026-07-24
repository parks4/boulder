"""Tests for :func:`boulder.api.live_config.adopt_live_config`.

Covers the "Boulder started with no preloaded file" gap: the Run Sweep
button and Scenario Pane are keyed off ``app.state.preloaded_config_path``,
which stays ``None`` for a browser-only session unless something adopts the
config the user pastes/uploads. These tests exercise both the helper
directly and its wiring into ``POST /api/configs/parse`` and
``POST /api/configs/upload``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.live_config import adopt_live_config  # noqa: E402
from boulder.api.main import create_app  # noqa: E402

_SCENARIO_YAML = """\
metadata:
  description: "test config"
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
  a:
    metadata:
      scenario_name: "A"
"""

_PLAIN_YAML = """\
metadata:
  description: "no scenarios here"
phases:
  gas:
    mechanism: gri30.yaml
network:
  - id: feed
    Reservoir:
      temperature: 298.15
      pressure: 101325
      composition: "CH4:1"
"""


def _client():
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    return client, app


class TestAdoptLiveConfigUnit:
    def test_first_call_creates_file_and_populates_state(self, tmp_path):
        app = create_app()
        app.state.preloaded_config_path = None

        class _Req:
            pass

        req = _Req()
        req.app = app

        adopt_live_config(
            req,
            raw={"scenarios": {"a": {}}},
            validated={"nodes": [], "connections": []},
            yaml_str=_SCENARIO_YAML,
            filename="pasted.yaml",
        )

        assert app.state.preloaded_config_path is not None
        path = app.state.preloaded_config_path
        assert path.endswith("pasted.yaml")
        assert app.state.preloaded_raw == {"scenarios": {"a": {}}}
        assert app.state.preloaded_yaml == _SCENARIO_YAML
        assert app.state.preloaded_filename == "pasted.yaml"

        with open(path, encoding="utf-8") as f:
            assert f.read() == _SCENARIO_YAML

    def test_second_call_overwrites_same_file(self):
        app = create_app()
        app.state.preloaded_config_path = None

        class _Req:
            pass

        req = _Req()
        req.app = app

        adopt_live_config(
            req, raw={}, validated={}, yaml_str=_PLAIN_YAML, filename="live.yaml"
        )
        first_path = app.state.preloaded_config_path

        adopt_live_config(
            req,
            raw={"scenarios": {"a": {}}},
            validated={},
            yaml_str=_SCENARIO_YAML,
            filename="live.yaml",
        )
        second_path = app.state.preloaded_config_path

        assert first_path == second_path
        with open(second_path, encoding="utf-8") as f:
            assert f.read() == _SCENARIO_YAML

    def test_noop_when_real_config_path_already_set(self, tmp_path):
        app = create_app()
        real_cfg = tmp_path / "real.yaml"
        real_cfg.write_text(_PLAIN_YAML, encoding="utf-8")
        app.state.preloaded_config_path = str(real_cfg)
        app.state.preloaded_raw = {"marker": "untouched"}

        class _Req:
            pass

        req = _Req()
        req.app = app

        adopt_live_config(
            req,
            raw={"scenarios": {"a": {}}},
            validated={},
            yaml_str=_SCENARIO_YAML,
            filename="pasted.yaml",
        )

        assert app.state.preloaded_config_path == str(real_cfg)
        assert app.state.preloaded_raw == {"marker": "untouched"}


class TestParseYamlAdoptsLiveConfig:
    def test_parse_with_no_preloaded_config_adopts_it(self):
        client, app = _client()
        try:
            assert app.state.preloaded_config_path is None

            resp = client.post("/api/configs/parse", json={"yaml": _SCENARIO_YAML})
            assert resp.status_code == 200, resp.text

            assert app.state.preloaded_config_path is not None
            assert app.state.preloaded_raw.get("scenarios") == {"a": {"metadata": {"scenario_name": "A"}}}
        finally:
            client.__exit__(None, None, None)

    def test_sweep_info_reflects_scenarios_after_parse(self):
        """GET /api/sweep sees a browser-pasted `scenarios:` block after Save.

        `can_run` still correctly requires an actual runner (none registered
        here) -- but `available`/`n_scenarios` must reflect the live config
        instead of staying stuck at the pre-adoption "no file" defaults.
        """
        client, app = _client()
        try:
            client.post("/api/configs/parse", json={"yaml": _SCENARIO_YAML})

            resp = client.get("/api/sweep")
            assert resp.status_code == 200, resp.text
            info = resp.json()
            assert info["available"] is True
            # Union run-set size: the baseline config + the one named scenario.
            assert info["n_scenarios"] == 2
            assert info["can_run"] is False  # no sweep_runner plugin registered
            assert info["reason"] == "No scenario runner available"
        finally:
            client.__exit__(None, None, None)

    def test_parse_is_noop_for_a_real_preloaded_config(self, tmp_path):
        real_cfg = tmp_path / "real.yaml"
        real_cfg.write_text(_PLAIN_YAML, encoding="utf-8")
        client, app = _client()
        try:
            app.state.preloaded_config_path = str(real_cfg)
            app.state.preloaded_raw = {"marker": "untouched"}

            resp = client.post("/api/configs/parse", json={"yaml": _SCENARIO_YAML})
            assert resp.status_code == 200, resp.text

            assert app.state.preloaded_config_path == str(real_cfg)
            assert app.state.preloaded_raw == {"marker": "untouched"}
        finally:
            client.__exit__(None, None, None)


class TestUploadConfigAdoptsLiveConfig:
    def test_upload_with_no_preloaded_config_adopts_it(self):
        client, app = _client()
        try:
            assert app.state.preloaded_config_path is None

            resp = client.post(
                "/api/configs/upload",
                files={"file": ("uploaded.yaml", _SCENARIO_YAML, "application/x-yaml")},
            )
            assert resp.status_code == 200, resp.text

            assert app.state.preloaded_config_path is not None
            assert app.state.preloaded_filename == "uploaded.yaml"
            assert app.state.preloaded_raw.get("scenarios")
        finally:
            client.__exit__(None, None, None)
