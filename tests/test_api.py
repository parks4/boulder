"""Tests for the FastAPI backend routes.

These tests use httpx.AsyncClient with the FastAPI test client
to validate all API endpoints without starting a real server.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from boulder.api.main import app as module_app  # noqa: E402
from boulder.api.main import create_app  # noqa: E402
from boulder.api.routes import simulations as simulation_routes  # noqa: E402

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_client():
    """Return an AsyncClient bound to a fresh FastAPI app."""
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self):
        async with _make_client() as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Config routes
# ---------------------------------------------------------------------------


class TestConfigRoutes:
    @pytest.mark.asyncio
    async def test_get_default_config(self):
        async with _make_client() as client:
            resp = await client.get("/api/configs/default")
            assert resp.status_code == 200
            data = resp.json()
            assert "config" in data
            assert "yaml" in data
            assert "nodes" in data["config"]
            assert isinstance(data["config"]["nodes"], list)

    @pytest.mark.asyncio
    async def test_get_preloaded_uses_request_app_state(self):
        """The /preloaded route must return values from the active request app state."""
        app = create_app()
        app.state.preloaded_config = {
            "nodes": [{"id": "from-request-app"}],
            "connections": [],
        }
        app.state.preloaded_yaml = "nodes: []"
        app.state.preloaded_filename = "request-app.yaml"

        module_app.state.preloaded_config = {
            "nodes": [{"id": "from-module-app"}],
            "connections": [],
        }
        module_app.state.preloaded_yaml = "nodes: [{id: wrong}]"
        module_app.state.preloaded_filename = "module-app.yaml"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/configs/preloaded")

        assert resp.status_code == 200
        data = resp.json()
        assert data["preloaded"] is True
        assert data["config"]["nodes"][0]["id"] == "from-request-app"
        assert data["yaml"] == "nodes: []"
        assert data["filename"] == "request-app.yaml"

    @pytest.mark.asyncio
    async def test_validate_config_valid(self):
        """A minimal valid config should pass validation."""
        config = {
            "nodes": [
                {
                    "id": "r1",
                    "type": "IdealGasReactor",
                    "properties": {"temperature": 1000, "pressure": 101325},
                }
            ],
            "connections": [],
        }
        async with _make_client() as client:
            resp = await client.post("/api/configs/validate", json={"config": config})
            assert resp.status_code == 200
            assert "config" in resp.json()

    @pytest.mark.asyncio
    async def test_validate_config_invalid_duplicate_id(self):
        """Duplicate node IDs should return 422."""
        config = {
            "nodes": [
                {"id": "r1", "type": "IdealGasReactor", "properties": {}},
                {"id": "r1", "type": "Reservoir", "properties": {}},
            ],
            "connections": [],
        }
        async with _make_client() as client:
            resp = await client.post("/api/configs/validate", json={"config": config})
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_validate_config_invalid_missing_nodes(self):
        """Config without nodes should return 422."""
        config = {"connections": []}
        async with _make_client() as client:
            resp = await client.post("/api/configs/validate", json={"config": config})
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_parse_yaml(self):
        yaml_str = (
            "network:\n"
            "  - id: feed\n"
            "    Reservoir:\n"
            "      temperature: 300\n"
            '      composition: "N2:1"\n'
            "  - id: reactor1\n"
            "    IdealGasReactor:\n"
            "      volume: 1.0e-3\n"
            "  - id: mfc1\n"
            "    MassFlowController:\n"
            "      mass_flow_rate: 0.001\n"
            "    source: feed\n"
            "    target: reactor1\n"
        )
        async with _make_client() as client:
            resp = await client.post("/api/configs/parse", json={"yaml": yaml_str})
            assert resp.status_code == 200
            data = resp.json()
            assert "config" in data
            nodes_by_id = {n["id"]: n for n in data["config"]["nodes"]}
            assert "reactor1" in nodes_by_id
            assert nodes_by_id["reactor1"]["type"] == "IdealGasReactor"

    @pytest.mark.asyncio
    async def test_parse_yaml_invalid(self):
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/parse", json={"yaml": "{{not yaml}}"}
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_export_config(self):
        config = {
            "nodes": [
                {
                    "id": "r1",
                    "type": "IdealGasReactor",
                    "properties": {"temperature": 1000},
                }
            ],
            "connections": [],
        }
        async with _make_client() as client:
            resp = await client.post("/api/configs/export", json={"config": config})
            assert resp.status_code == 200
            data = resp.json()
            assert "yaml" in data
            assert "network:" in data["yaml"]
            assert "r1" in data["yaml"]
            assert "IdealGasReactor" in data["yaml"]


# ---------------------------------------------------------------------------
# Mechanism routes
# ---------------------------------------------------------------------------


class TestMechanismRoutes:
    @pytest.mark.asyncio
    async def test_list_mechanisms(self):
        async with _make_client() as client:
            resp = await client.get("/api/mechanisms")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            # At minimum gri30.yaml should be available
            labels = [m.get("label", m.get("value", "")) for m in data]
            assert any("gri30" in label.lower() for label in labels)


# ---------------------------------------------------------------------------
# Graph routes
# ---------------------------------------------------------------------------


class TestGraphRoutes:
    @pytest.mark.asyncio
    async def test_get_elements_empty(self):
        async with _make_client() as client:
            resp = await client.post(
                "/api/graph/elements",
                json={"config": {"nodes": [], "connections": []}},
            )
            assert resp.status_code == 200
            assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_elements_with_nodes(self):
        config = {
            "nodes": [
                {
                    "id": "r1",
                    "type": "IdealGasReactor",
                    "properties": {"temperature": 1000},
                },
                {"id": "r2", "type": "Reservoir", "properties": {}},
            ],
            "connections": [
                {
                    "id": "mfc1",
                    "type": "MassFlowController",
                    "source": "r1",
                    "target": "r2",
                    "properties": {"mass_flow_rate": 0.1},
                }
            ],
        }
        async with _make_client() as client:
            resp = await client.post("/api/graph/elements", json={"config": config})
            assert resp.status_code == 200
            elements = resp.json()
            # 2 nodes + 1 edge = 3 elements
            assert len(elements) == 3

    @pytest.mark.asyncio
    async def test_get_stylesheet_light(self):
        async with _make_client() as client:
            resp = await client.get("/api/graph/stylesheet?theme=light")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) > 0

    @pytest.mark.asyncio
    async def test_get_stylesheet_dark(self):
        async with _make_client() as client:
            resp = await client.get("/api/graph/stylesheet?theme=dark")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Plugin routes
# ---------------------------------------------------------------------------


class TestPluginRoutes:
    @pytest.mark.asyncio
    async def test_list_plugins(self):
        async with _make_client() as client:
            resp = await client.get("/api/plugins")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_render_unknown_plugin(self):
        async with _make_client() as client:
            resp = await client.post(
                "/api/plugins/nonexistent/render",
                json={"theme": "light"},
            )
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Simulation routes
# ---------------------------------------------------------------------------


class TestSimulationRoutes:
    @pytest.mark.asyncio
    async def test_start_simulation_uses_settings_when_fields_omitted(
        self, monkeypatch
    ):
        """Start route must use config settings when time fields are omitted."""
        simulation_routes._simulations.clear()
        captured: dict[str, float] = {}

        class DummyConverter:
            def __init__(self, mechanism: str):
                self.mechanism = mechanism

        class DummyWorker:
            def start_simulation(self, converter, config, simulation_time, time_step):
                captured["simulation_time"] = simulation_time
                captured["time_step"] = time_step

        monkeypatch.setattr(simulation_routes, "DualCanteraConverter", DummyConverter)
        monkeypatch.setattr(simulation_routes, "SimulationWorker", DummyWorker)

        config = {
            "nodes": [],
            "connections": [],
            "settings": {"end_time": 12.5, "dt": 0.25},
        }
        async with _make_client() as client:
            resp = await client.post("/api/simulations", json={"config": config})

        assert resp.status_code == 200
        assert captured["simulation_time"] == 12.5
        assert captured["time_step"] == 0.25

        simulation_routes._simulations.clear()

    @pytest.mark.asyncio
    async def test_start_simulation_prefers_explicit_request_values(self, monkeypatch):
        """Start route must prefer explicit request values over config settings."""
        simulation_routes._simulations.clear()
        captured: dict[str, float] = {}

        class DummyConverter:
            def __init__(self, mechanism: str):
                self.mechanism = mechanism

        class DummyWorker:
            def start_simulation(self, converter, config, simulation_time, time_step):
                captured["simulation_time"] = simulation_time
                captured["time_step"] = time_step

        monkeypatch.setattr(simulation_routes, "DualCanteraConverter", DummyConverter)
        monkeypatch.setattr(simulation_routes, "SimulationWorker", DummyWorker)

        config = {
            "nodes": [],
            "connections": [],
            "settings": {"end_time": 99.0, "dt": 9.0},
        }
        payload = {
            "config": config,
            "simulation_time": 3.0,
            "time_step": 0.05,
        }
        async with _make_client() as client:
            resp = await client.post("/api/simulations", json=payload)

        assert resp.status_code == 200
        assert captured["simulation_time"] == 3.0
        assert captured["time_step"] == 0.05

        simulation_routes._simulations.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_time_step", [0.0, -1.0])
    async def test_start_simulation_rejects_non_positive_time_step(
        self, monkeypatch, invalid_time_step: float
    ):
        """Start route must reject zero/negative time_step to avoid non-progress loops."""
        simulation_routes._simulations.clear()
        worker_called = False

        class DummyConverter:
            def __init__(self, mechanism: str):
                self.mechanism = mechanism

        class DummyWorker:
            def start_simulation(self, converter, config, simulation_time, time_step):
                nonlocal worker_called
                worker_called = True

        monkeypatch.setattr(simulation_routes, "DualCanteraConverter", DummyConverter)
        monkeypatch.setattr(simulation_routes, "SimulationWorker", DummyWorker)

        config = {
            "nodes": [],
            "connections": [],
            "settings": {"end_time": 10.0, "dt": 1.0},
        }
        payload = {"config": config, "time_step": invalid_time_step}

        async with _make_client() as client:
            resp = await client.post("/api/simulations", json=payload)

        assert resp.status_code == 422
        assert resp.json()["detail"] == "time_step must be > 0"
        assert worker_called is False
        simulation_routes._simulations.clear()


# ---------------------------------------------------------------------------
# POST /api/configs/sync
# ---------------------------------------------------------------------------

_SYNC_YAML = (
    "phases:\n"
    "  gas:\n"
    "    mechanism: gri30.yaml\n"
    "network:\n"
    "  - id: inlet\n"
    "    Reservoir:\n"
    "      temperature: 298.15 K\n"
    "      pressure: 1 atm\n"
    "      composition: CH4:1\n"
    "  - id: pfr\n"
    "    IdealGasReactor:\n"
    "      volume: 0.001\n"
    "  - id: feed\n"
    "    MassFlowController:\n"
    "      mass_flow_rate: 10 kg/h\n"
    "    source: inlet\n"
    "    target: pfr\n"
)

_SYNC_CONFIG = {
    "nodes": [
        {
            "id": "inlet",
            "type": "Reservoir",
            "properties": {
                "temperature": 298.15,
                "pressure": 101325.0,
                "composition": "CH4:1",
            },
        },
        {"id": "pfr", "type": "IdealGasReactor", "properties": {"volume": 0.001}},
    ],
    "connections": [
        {
            "id": "feed",
            "type": "MassFlowController",
            "source": "inlet",
            "target": "pfr",
            "properties": {"mass_flow_rate": 10 / 3600},
        },
    ],
}


class TestSyncConfigRoute:
    @pytest.mark.asyncio
    async def test_sync_returns_merged_yaml_with_units_preserved(self):
        """Assert /api/configs/sync returns 200 with original unit strings.

        Checks that 'yaml' contains '1 atm', '298.15 K', 'kg/h' verbatim
        and that 'warnings' is an empty list when no values changed.
        """
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/sync",
                json={"config": _SYNC_CONFIG, "original_yaml": _SYNC_YAML},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "yaml" in body
        assert body["warnings"] == []
        # Original unit strings preserved
        assert "1 atm" in body["yaml"]
        assert "298.15 K" in body["yaml"]
        assert "kg/h" in body["yaml"]

    @pytest.mark.asyncio
    async def test_sync_updates_changed_pressure_in_original_unit(self):
        """Assert doubled pressure appears as '2 atm', not as a bare SI float.

        Original has 'pressure: 1 atm'; config sets pressure to 202650 Pa.
        Merged YAML must contain '2 atm' and not '202650'.
        """
        config = {
            "nodes": [
                {
                    "id": "inlet",
                    "type": "Reservoir",
                    "properties": {
                        "temperature": 298.15,
                        "pressure": 202650.0,
                        "composition": "CH4:1",
                    },
                },
                {
                    "id": "pfr",
                    "type": "IdealGasReactor",
                    "properties": {"volume": 0.001},
                },
            ],
            "connections": [
                {
                    "id": "feed",
                    "type": "MassFlowController",
                    "source": "inlet",
                    "target": "pfr",
                    "properties": {"mass_flow_rate": 10 / 3600},
                },
            ],
        }
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/sync",
                json={"config": config, "original_yaml": _SYNC_YAML},
            )
        assert resp.status_code == 200
        yaml_out = resp.json()["yaml"]
        assert "2 atm" in yaml_out
        assert "202650" not in yaml_out

    @pytest.mark.asyncio
    async def test_sync_filters_synthesized_nodes(self):
        """Assert synthesized nodes are absent from the merged YAML.

        Config contains pfr_ambient with __synthesized=True.
        Response YAML must not contain 'pfr_ambient'.
        """
        config = {
            "nodes": [
                {
                    "id": "inlet",
                    "type": "Reservoir",
                    "properties": {
                        "temperature": 298.15,
                        "pressure": 101325.0,
                        "composition": "CH4:1",
                    },
                },
                {
                    "id": "pfr",
                    "type": "IdealGasReactor",
                    "properties": {"volume": 0.001},
                },
                {
                    "id": "pfr_ambient",
                    "type": "Reservoir",
                    "properties": {"temperature": 298.15},
                    "__synthesized": True,
                },
            ],
            "connections": [
                {
                    "id": "feed",
                    "type": "MassFlowController",
                    "source": "inlet",
                    "target": "pfr",
                    "properties": {"mass_flow_rate": 10 / 3600},
                },
            ],
        }
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/sync",
                json={"config": config, "original_yaml": _SYNC_YAML},
            )
        assert resp.status_code == 200
        assert "pfr_ambient" not in resp.json()["yaml"]

    @pytest.mark.asyncio
    async def test_sync_keeps_gui_added_node(self):
        """Assert GUI-added node (no __synthesized flag) appears in merged YAML.

        Config adds 'new_gui_node' which is absent from original_yaml.
        Response YAML must contain 'new_gui_node'.
        """
        config = {
            "nodes": [
                {
                    "id": "inlet",
                    "type": "Reservoir",
                    "properties": {
                        "temperature": 298.15,
                        "pressure": 101325.0,
                        "composition": "CH4:1",
                    },
                },
                {
                    "id": "pfr",
                    "type": "IdealGasReactor",
                    "properties": {"volume": 0.001},
                },
                {
                    "id": "new_gui_node",
                    "type": "IdealGasReactor",
                    "properties": {"volume": 0.002},
                },
            ],
            "connections": [
                {
                    "id": "feed",
                    "type": "MassFlowController",
                    "source": "inlet",
                    "target": "pfr",
                    "properties": {"mass_flow_rate": 10 / 3600},
                },
            ],
        }
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/sync",
                json={"config": config, "original_yaml": _SYNC_YAML},
            )
        assert resp.status_code == 200
        assert "new_gui_node" in resp.json()["yaml"]

    @pytest.mark.asyncio
    async def test_sync_returns_422_on_inline_ports(self):
        """Assert inline port shortcuts in original_yaml return HTTP 422.

        YAML with 'inlet:' on a node triggers the inline-port guard.
        Response detail must mention 'inline'.
        """
        yaml_with_ports = (
            "phases:\n  gas:\n    mechanism: gri30.yaml\n"
            "network:\n"
            "  - id: tube\n"
            "    CustomReactor:\n"
            "      length: 1.0\n"
            "      inlet:\n"
            "        from: feed\n"
            "        mass_flow_rate: 0.001\n"
        )
        config = {
            "nodes": [
                {"id": "tube", "type": "CustomReactor", "properties": {"length": 1.0}}
            ],
            "connections": [],
        }
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/sync",
                json={"config": config, "original_yaml": yaml_with_ports},
            )
        assert resp.status_code == 422
        assert "inline" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_sync_returns_422_on_shape_conflict(self):
        """Assert network: -> stages: shape change returns HTTP 422.

        Original uses network:; config has a non-default group implying stages:.
        Response detail must mention 'shape'.
        """
        config_with_stages = {
            "nodes": [
                {
                    **{
                        "id": "inlet",
                        "type": "Reservoir",
                        "properties": {
                            "temperature": 298.15,
                            "pressure": 101325.0,
                            "composition": "CH4:1",
                        },
                    },
                    "group": "s1",
                },
            ],
            "connections": [],
            "groups": {
                "s1": {
                    "mechanism": "gri30.yaml",
                    "solve": "equilibrate",
                    "stage_order": 0,
                },
            },
        }
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/sync",
                json={"config": config_with_stages, "original_yaml": _SYNC_YAML},
            )
        assert resp.status_code == 422
        assert "shape" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_sync_returns_422_on_invalid_original_yaml(self):
        """Assert malformed original_yaml returns a non-200 status.

        An unclosed bracket causes a YAML parse error.
        Response status must be 422 or 500.
        """
        async with _make_client() as client:
            resp = await client.post(
                "/api/configs/sync",
                json={
                    "config": _SYNC_CONFIG,
                    "original_yaml": "invalid: yaml: [unclosed bracket",
                },
            )
        assert resp.status_code in (422, 500)
