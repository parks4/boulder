"""Tests for simulation memory cleanup to prevent memory leaks.

These tests verify that completed simulations are properly removed
from memory to prevent unbounded retention of result payloads.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402
from boulder.api.routes.simulations import _simulations  # noqa: E402


def _make_client():
    """Return an AsyncClient bound to a fresh FastAPI app."""
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def minimal_config():
    """Return a minimal valid reactor network config."""
    return {
        "nodes": [
            {
                "id": "reactor1",
                "type": "IdealGasReactor",
                "properties": {
                    "temperature": 1000,
                    "pressure": 101325,
                    "composition": "CH4:1,O2:2,N2:7.52",
                },
            }
        ],
        "connections": [],
        "settings": {"end_time": 0.1, "dt": 0.05},
    }


class TestSimulationCleanup:
    """Test suite for simulation memory cleanup."""

    @pytest.mark.asyncio
    async def test_simulation_deleted_after_stop(self, minimal_config):
        """Verify that stopping a simulation removes it from memory."""
        # Clear any existing simulations
        _simulations.clear()

        async with _make_client() as client:
            # Start a simulation
            resp = await client.post(
                "/api/simulations",
                json={
                    "config": minimal_config,
                    "simulation_time": 0.1,
                    "time_step": 0.05,
                },
            )
            assert resp.status_code == 200
            sim_id = resp.json()["simulation_id"]

            # Verify the simulation is in memory
            assert sim_id in _simulations
            initial_count = len(_simulations)
            assert initial_count == 1

            # Stop the simulation
            resp = await client.delete(f"/api/simulations/{sim_id}")
            assert resp.status_code == 200
            assert resp.json()["stopped"] is True

            # Verify the simulation was removed from memory
            assert sim_id not in _simulations
            assert len(_simulations) == initial_count - 1

    @pytest.mark.asyncio
    async def test_simulation_cleanup_with_query_param(self, minimal_config):
        """Verify that cleanup=true removes completed simulations."""
        _simulations.clear()

        async with _make_client() as client:
            # Start a simulation
            resp = await client.post(
                "/api/simulations",
                json={
                    "config": minimal_config,
                    "simulation_time": 0.1,
                    "time_step": 0.05,
                },
            )
            assert resp.status_code == 200
            sim_id = resp.json()["simulation_id"]

            # Verify it's in memory
            assert sim_id in _simulations

            # Wait for completion by polling results
            import asyncio

            max_attempts = 20
            for _ in range(max_attempts):
                resp = await client.get(f"/api/simulations/{sim_id}/results")
                data = resp.json()
                if data.get("is_complete") or data.get("error_message"):
                    break
                await asyncio.sleep(0.2)

            # Get results with cleanup=true
            resp = await client.get(f"/api/simulations/{sim_id}/results?cleanup=true")
            assert resp.status_code == 200

            # Verify the simulation was removed from memory
            assert sim_id not in _simulations

    @pytest.mark.asyncio
    async def test_cleanup_endpoint_removes_completed(self, minimal_config):
        """Verify that the cleanup endpoint removes completed simulations."""
        _simulations.clear()

        async with _make_client() as client:
            # Start multiple simulations
            sim_ids = []
            for _ in range(2):
                resp = await client.post(
                    "/api/simulations",
                    json={
                        "config": minimal_config,
                        "simulation_time": 0.1,
                        "time_step": 0.05,
                    },
                )
                assert resp.status_code == 200
                sim_ids.append(resp.json()["simulation_id"])

            # Wait for all to complete
            import asyncio

            for sim_id in sim_ids:
                max_attempts = 20
                for _ in range(max_attempts):
                    resp = await client.get(f"/api/simulations/{sim_id}/results")
                    data = resp.json()
                    if data.get("is_complete") or data.get("error_message"):
                        break
                    await asyncio.sleep(0.2)

            # All simulations should still be in memory
            assert len(_simulations) == 2

            # Call cleanup endpoint
            resp = await client.post("/api/simulations/cleanup")
            assert resp.status_code == 200
            data = resp.json()

            # Both completed simulations should be removed
            assert data["removed"] == 2
            assert data["remaining"] == 0
            assert len(_simulations) == 0

    @pytest.mark.asyncio
    async def test_cleanup_endpoint_respects_max_age(self, minimal_config):
        """Verify that cleanup endpoint respects max_age_seconds parameter."""
        _simulations.clear()

        async with _make_client() as client:
            # Start a simulation
            resp = await client.post(
                "/api/simulations",
                json={
                    "config": minimal_config,
                    "simulation_time": 0.1,
                    "time_step": 0.05,
                },
            )
            assert resp.status_code == 200
            sim_id = resp.json()["simulation_id"]

            # Wait for completion
            import asyncio

            max_attempts = 20
            for _ in range(max_attempts):
                resp = await client.get(f"/api/simulations/{sim_id}/results")
                data = resp.json()
                if data.get("is_complete") or data.get("error_message"):
                    break
                await asyncio.sleep(0.2)

            # Try to cleanup with max_age=1000 seconds (simulation is too recent)
            resp = await client.post("/api/simulations/cleanup?max_age_seconds=1000")
            assert resp.status_code == 200
            data = resp.json()

            # Should not be removed because it's not old enough
            assert data["removed"] == 0
            assert data["remaining"] == 1

            # Try to cleanup with max_age=0 seconds (all completed should go)
            resp = await client.post("/api/simulations/cleanup?max_age_seconds=0")
            assert resp.status_code == 200
            data = resp.json()

            # Now it should be removed
            assert data["removed"] == 1
            assert data["remaining"] == 0

    @pytest.mark.asyncio
    async def test_repeated_simulations_dont_accumulate(self, minimal_config):
        """Verify that running many simulations doesn't cause unbounded memory growth."""
        _simulations.clear()

        async with _make_client() as client:
            num_simulations = 5

            for i in range(num_simulations):
                # Start simulation
                resp = await client.post(
                    "/api/simulations",
                    json={
                        "config": minimal_config,
                        "simulation_time": 0.1,
                        "time_step": 0.05,
                    },
                )
                assert resp.status_code == 200
                sim_id = resp.json()["simulation_id"]

                # Wait for completion
                import asyncio

                max_attempts = 20
                for _ in range(max_attempts):
                    resp = await client.get(f"/api/simulations/{sim_id}/results")
                    data = resp.json()
                    if data.get("is_complete") or data.get("error_message"):
                        break
                    await asyncio.sleep(0.2)

                # Get results with cleanup to prevent accumulation
                resp = await client.get(
                    f"/api/simulations/{sim_id}/results?cleanup=true"
                )
                assert resp.status_code == 200

            # After cleanup on each iteration, dictionary should be empty
            assert len(_simulations) == 0

    @pytest.mark.asyncio
    async def test_simulation_stores_timestamp(self, minimal_config):
        """Verify that simulations are stored with creation timestamp."""
        _simulations.clear()

        async with _make_client() as client:
            # Start a simulation
            resp = await client.post(
                "/api/simulations",
                json={
                    "config": minimal_config,
                    "simulation_time": 0.1,
                    "time_step": 0.05,
                },
            )
            assert resp.status_code == 200
            sim_id = resp.json()["simulation_id"]

            # Verify the stored format is (worker, timestamp)
            assert sim_id in _simulations
            entry = _simulations[sim_id]
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            worker, timestamp = entry
            assert isinstance(timestamp, float)
            assert timestamp > 0

            # Clean up
            await client.delete(f"/api/simulations/{sim_id}")
