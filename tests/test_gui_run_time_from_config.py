"""A GUI Run with the Simulate card untouched solves the config a headless run solves."""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from boulder.api.main import create_app  # noqa: E402
from boulder.api.routes import simulations as simulation_routes  # noqa: E402
from boulder.sweep_runner import (  # noqa: E402
    EntryOutcome,
    prepare_entry,
    with_time_overrides,
)
from httpx import ASGITransport, AsyncClient  # noqa: E402


def _config(solver: Dict[str, Any], **settings: Any) -> Dict[str, Any]:
    return {
        "metadata": {},
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "settings": {"solver": solver, **settings},
        "network": [
            {
                "id": "reactor",
                "IdealGasReactor": {
                    "volume": 1.0,
                    "initial": {
                        "temperature": 500,
                        "pressure": 101325,
                        "composition": "N2:1",
                    },
                },
            }
        ],
    }


# (a) advance_time, (b) settings.dt declared, (c) no advance_time, settings.end_time.
_CASES = {
    "advance_time": (_config({"kind": "advance", "advance_time": 2.0}), 2.0, 1.0),
    "settings_dt": (
        _config({"kind": "advance", "advance_time": 2.0}, dt=0.25),
        2.0,
        0.25,
    ),
    "end_time": (_config({"kind": "advance"}, end_time=3.0), 3.0, 0.3),
}


async def _post(
    raw: Dict[str, Any], body: Dict[str, Any], monkeypatch
) -> Dict[str, Any]:
    captured: Dict[str, Any] = {}

    def fake_run_set(raw_cfg, config_path, **kwargs):
        captured["raw"] = raw_cfg
        (sid,) = kwargs["only"]
        return [EntryOutcome(sid, "fp", False, {"times": [0.0]})]

    monkeypatch.setattr(simulation_routes, "run_set", fake_run_set)
    simulation_routes._simulations.clear()
    app = create_app()
    app.state.preloaded_raw = copy.deepcopy(raw)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/simulations", json=body)
        assert resp.status_code == 200, resp.text
        sim_id = resp.json()["simulation_id"]
        for _ in range(100):
            res = (await client.get(f"/api/simulations/{sim_id}/results")).json()
            if res["status"] != "running":
                break
            await asyncio.sleep(0.05)
    simulation_routes._simulations.clear()
    return captured["raw"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(_CASES))
async def test_untouched_card_fields_solve_the_headless_config(
    name, monkeypatch
) -> None:
    """Card fields equal to what the config resolves to leave the fingerprint unchanged.

    The card sends its simulation time and step with every flat ``advance`` run;
    sent as the config's own values (a, b, c) the run is the headless one.
    """
    raw, sim_time, step = _CASES[name]
    headless = prepare_entry(copy.deepcopy(raw), "BASELINE")[2]

    sent = await _post(
        raw, {"simulation_time": sim_time, "time_step": step}, monkeypatch
    )

    assert sent == raw
    assert prepare_entry(sent, "BASELINE")[2] == headless


@pytest.mark.asyncio
async def test_edited_card_field_still_overrides(monkeypatch) -> None:
    """A user edit of the run time is applied and changes the fingerprint."""
    raw, _, step = _CASES["end_time"]
    headless = prepare_entry(copy.deepcopy(raw), "BASELINE")[2]

    sent = await _post(raw, {"simulation_time": 5.0, "time_step": step}, monkeypatch)

    assert sent["settings"]["solver"]["advance_time"] == 5.0
    assert prepare_entry(sent, "BASELINE")[2] != headless


def test_staged_config_still_rejects_an_override_equal_to_its_window() -> None:
    """Staged configs keep today's behaviour: any time override is refused."""
    staged = _config({"kind": "advance", "advance_time": 2.0})
    staged["stages"] = {"s1": {"solver": {"kind": "advance", "advance_time": 2.0}}}
    with pytest.raises(ValueError, match="staged"):
        with_time_overrides(staged, 2.0, None)
