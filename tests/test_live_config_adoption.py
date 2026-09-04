"""Tests for :func:`boulder.api.live_config.adopt_live_config`.

Covers the "Boulder started with no preloaded file" gap: the Run Sweep
button and Scenario Pane are keyed off ``app.state.preloaded_config_path``,
which stays ``None`` for a browser-only session unless something adopts the
config the user pastes/uploads. These tests exercise both the helper
directly and its wiring into ``POST /api/configs/parse`` and
``POST /api/configs/upload``.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.live_config import adopt_live_config  # noqa: E402
from boulder.api.main import create_app  # noqa: E402
from boulder.api.routes.configs import _to_plain_dict  # noqa: E402
from boulder.config import load_yaml_string_with_comments  # noqa: E402

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

# A flow network whose outlet declares no pressure: `normalize()` propagates
# the process pressure onto it (in place), which is exactly what the adopted
# *raw* base must not contain -- a scenario overlay setting another outlet
# pressure would otherwise conflict with the propagated one.
_OUTLET_YAML = """\
phases:
  gas:
    mechanism: gri30.yaml
network:
  - id: feed
    Reservoir:
      temperature: 300 K
      pressure: 101325 Pa
      composition: "CH4:0.5,O2:1.0,N2:3.76"
  - id: reactor
    IdealGasConstPressureMoleReactor:
      volume: 1.0e-3 m**3
      initial:
        temperature: 1475 K
        pressure: 101325 Pa
        composition: "CO2:0.04476,H2O:0.08951,N2:0.86573"
  - id: outlet
    OutletSink: {}
  - id: feed_to_reactor
    MassFlowController:
      mass_flow_rate: 1.0e-4 kg/s
    source: feed
    target: reactor
  - id: reactor_to_outlet
    PressureController:
      pressure_coeff: 0.0
      master: feed_to_reactor
    source: reactor
    target: outlet
scenarios:
  high_p:
    network:
      - id: outlet
        OutletSink:
          pressure: 200000 Pa
"""


def _outlet_node(raw):
    return next(n for n in raw["network"] if n["id"] == "outlet")


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

    def test_real_config_path_takes_content_keeps_location(self, tmp_path):
        """An in-place edit of a CLI-provided file updates content, not location.

        The base config the sweep and the Scenario Pane work from must follow
        the edit; the path (and so the result store, its identity and any
        relative paths) must stay with the user's file, which is never written.
        """
        app = create_app()
        real_cfg = tmp_path / "real.yaml"
        real_cfg.write_text(_PLAIN_YAML, encoding="utf-8")
        app.state.preloaded_config_path = str(real_cfg)
        app.state.preloaded_filename = "real.yaml"
        app.state.preloaded_raw = {"marker": "startup"}

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

        assert app.state.preloaded_raw == {"scenarios": {"a": {}}}
        assert app.state.preloaded_config == {"nodes": [], "connections": []}
        assert app.state.preloaded_yaml == _SCENARIO_YAML
        assert app.state.preloaded_config_path == str(real_cfg)
        assert app.state.preloaded_filename == "real.yaml"
        assert real_cfg.read_text(encoding="utf-8") == _PLAIN_YAML
        assert not list(tmp_path.glob("**/pasted.yaml"))


class TestParseYamlAdoptsLiveConfig:
    def test_parse_with_no_preloaded_config_adopts_it(self):
        client, app = _client()
        try:
            assert app.state.preloaded_config_path is None

            resp = client.post("/api/configs/parse", json={"yaml": _SCENARIO_YAML})
            assert resp.status_code == 200, resp.text

            assert app.state.preloaded_config_path is not None
            assert app.state.preloaded_raw.get("scenarios") == {
                "a": {"metadata": {"scenario_name": "A"}}
            }
        finally:
            client.__exit__(None, None, None)

    def test_sweep_info_reflects_scenarios_after_parse(self):
        """GET /api/sweep sees a browser-pasted `scenarios:` block after Save.

        `available`/`n_scenarios`/`can_run` must reflect the live config
        instead of staying stuck at the pre-adoption "no file" defaults. Run
        Sweep runs in-process now -- no external runner to register/check for.
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
            assert info["can_run"] is True
            assert info["reason"] == "Run 2 scenarios"
        finally:
            client.__exit__(None, None, None)

    def test_parse_updates_content_for_a_real_preloaded_config(self, tmp_path):
        real_cfg = tmp_path / "real.yaml"
        real_cfg.write_text(_PLAIN_YAML, encoding="utf-8")
        client, app = _client()
        try:
            app.state.preloaded_config_path = str(real_cfg)
            app.state.preloaded_raw = {"marker": "startup"}

            resp = client.post("/api/configs/parse", json={"yaml": _SCENARIO_YAML})
            assert resp.status_code == 200, resp.text

            assert app.state.preloaded_config_path == str(real_cfg)
            assert app.state.preloaded_raw.get("scenarios") == {
                "a": {"metadata": {"scenario_name": "A"}}
            }
            assert app.state.preloaded_yaml == _SCENARIO_YAML
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

    def test_upload_replaces_a_real_preloaded_config(self, tmp_path):
        """An upload is adopted even when the server was started with a real file.

        Otherwise the Scenario Pane, Run Sweep and the result cache keep
        serving the startup file's scenarios for whatever the user uploads
        afterwards. The startup file itself is left untouched.
        """
        real_cfg = tmp_path / "real.yaml"
        real_cfg.write_text(_PLAIN_YAML, encoding="utf-8")
        client, app = _client()
        try:
            app.state.preloaded_config_path = str(real_cfg)
            app.state.preloaded_filename = "real.yaml"
            app.state.preloaded_raw = {"marker": "startup file"}

            resp = client.post(
                "/api/configs/upload",
                files={"file": ("uploaded.yaml", _SCENARIO_YAML, "application/x-yaml")},
            )
            assert resp.status_code == 200, resp.text

            assert app.state.preloaded_config_path != str(real_cfg)
            assert app.state.preloaded_filename == "uploaded.yaml"
            assert list(app.state.preloaded_raw.get("scenarios", {})) == ["a"]
            assert real_cfg.read_text(encoding="utf-8") == _PLAIN_YAML
        finally:
            client.__exit__(None, None, None)


class TestAdoptedRawIsUnNormalized:
    """The adopted `preloaded_raw` is the config as authored, not the normalized one.

    `normalize()` mutates its argument in place; if that dict were adopted as
    the Run Sweep base config, every node would carry a propagated process
    pressure and a scenario overriding the outlet pressure would fail with a
    pressure conflict.
    """

    def test_upload_adopts_the_authored_config(self):
        client, app = _client()
        try:
            resp = client.post(
                "/api/configs/upload",
                files={"file": ("outlet.yaml", _OUTLET_YAML, "application/x-yaml")},
            )
            assert resp.status_code == 200, resp.text

            raw = app.state.preloaded_raw
            assert "pressure" not in _outlet_node(raw)["OutletSink"]
            assert raw == _to_plain_dict(load_yaml_string_with_comments(_OUTLET_YAML))
            # The response itself is still the normalized, validated config.
            assert resp.json()["config"]["nodes"]
        finally:
            client.__exit__(None, None, None)

    def test_parse_adopts_the_authored_config(self):
        client, app = _client()
        try:
            resp = client.post("/api/configs/parse", json={"yaml": _OUTLET_YAML})
            assert resp.status_code == 200, resp.text

            raw = app.state.preloaded_raw
            assert "pressure" not in _outlet_node(raw)["OutletSink"]
            assert raw == _to_plain_dict(load_yaml_string_with_comments(_OUTLET_YAML))
        finally:
            client.__exit__(None, None, None)


_LOW_P_SCENARIO = """\
  low_p:
    network:
      - id: outlet
        OutletSink:
          pressure: 50000 Pa
"""


def _client_started_with(cfg_path):
    """Start the app the way the CLI does, so the lifespan preloads *cfg_path*."""
    os.environ["BOULDER_CONFIG_PATH"] = str(cfg_path)
    try:
        app = create_app()
        client = TestClient(app)
        client.__enter__()
    finally:
        del os.environ["BOULDER_CONFIG_PATH"]
    return client, app


class TestEditedScenariosReachThePane:
    """Saving a `scenarios:` edit on a server started with a real file.

    The Scenario Pane re-seeds from ``GET /api/scenarios`` after a YAML-pane
    Save and Run Sweep merges overlays onto the server's base config: both must
    see the edited config, while the result store stays where the file is.
    """

    def test_parse_adds_a_scenario_without_moving_the_store(self, tmp_path):
        cfg = tmp_path / "base.yaml"
        cfg.write_text(_OUTLET_YAML, encoding="utf-8")
        client, app = _client_started_with(cfg)
        try:
            before = client.get("/api/scenarios").json()
            assert before["authored_ids"] == ["BASELINE", "high_p"]

            resp = client.post(
                "/api/configs/parse", json={"yaml": _OUTLET_YAML + _LOW_P_SCENARIO}
            )
            assert resp.status_code == 200, resp.text

            after = client.get("/api/scenarios").json()
            assert after["authored_ids"] == ["BASELINE", "high_p", "low_p"]
            assert after["store"] == before["store"] == "base"
            assert app.state.preloaded_config_path == str(cfg)

            info = client.get("/api/sweep").json()
            assert info["n_scenarios"] == 3
            assert info["can_run"] is True

            # The base network the sweep merges onto is the edited one, still
            # un-normalized (no propagated pressure on the outlet).
            assert "pressure" not in _outlet_node(app.state.preloaded_raw)["OutletSink"]
            assert cfg.read_text(encoding="utf-8") == _OUTLET_YAML
        finally:
            client.__exit__(None, None, None)
