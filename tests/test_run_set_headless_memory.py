"""A headless ``run_set`` keeps no per-entry payload, parses a mechanism once and frees networks.

``EntryOutcome.gui`` carries the GUI worker payload, and a cached entry reads it
back from the store. Only the GUI routes (and ``run --download``) look at it, so
``run_set`` fills it on request (``keep_payload``). Without that, every entry's
payload stayed alive until the sweep ended: peak memory grew with entry count.
The remaining native-memory growth (a second mechanism parse in the store writer, the
previous entry's network alive through the next build) is checked deterministically.
"""

from __future__ import annotations

import copy
import gc
from pathlib import Path
from typing import Any, Dict, List

import cantera as ct
import pytest

pytest.importorskip("h5py")

from boulder import cantera_converter, result_cache, scenario_store  # noqa: E402
from boulder.cantera_converter import (
    BoulderPlugins,  # noqa: E402
    DualCanteraConverter,  # noqa: E402
)
from boulder.ctutils import derive_solution, parse_mechanism_spec  # noqa: E402
from boulder.live_simulation import get_live_simulation  # noqa: E402
from boulder.sweep_runner import run_set  # noqa: E402


def _gri(*ids: str) -> Dict[str, Any]:
    """Build a one-reactor gri30 config with one empty scenario per id."""
    return {
        "metadata": {},
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "network": [
            {
                "id": "r",
                "IdealGasReactor": {
                    "volume": 1.0,
                    "initial": {
                        "temperature": 1000,
                        "pressure": 101325,
                        "composition": "CH4:1, O2:2, N2:7.5",
                    },
                },
            }
        ],
        "settings": {"end_time": 1e-3, "dt": 1e-4},
        "scenarios": {i: {} for i in ids},
    }


@pytest.fixture(autouse=True)
def bare_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """No discovered host plugin or contributor: the default converter, a clean registry."""
    monkeypatch.setattr(cantera_converter, "_PLUGIN_CACHE", BoulderPlugins())
    registry = result_cache.get_cache_contributor_registry()
    monkeypatch.setattr(registry, "contributors", [])


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    path = tmp_path / "model.yaml"
    path.write_text("metadata: {}\n", encoding="utf-8")
    return path


def test_headless_outcomes_carry_no_payload_and_gui_callers_can_ask(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Headless outcomes are empty; ``keep_payload`` fills them.

    Asserts: default outcomes have empty ``gui`` (solved and cached; the store is
    not read back for a cached entry); ``keep_payload=True`` fills both.
    """
    raw = _gri("a")
    solved = run_set(copy.deepcopy(raw), cfg, only={"a"})
    assert [(o.cached, o.gui) for o in solved] == [(False, {})]

    reads: List[str] = []
    real = scenario_store.read_entry

    def spy(*args: Any, **kwargs: Any) -> Any:
        reads.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(scenario_store, "read_entry", spy)
    cached = run_set(copy.deepcopy(raw), cfg, only={"a"})
    assert [(o.cached, o.gui) for o in cached] == [(True, {})]
    assert reads == []
    kept = run_set(copy.deepcopy(raw), cfg, only={"a"}, keep_payload=True)
    assert kept[0].cached and kept[0].gui["code_str"]

    fresh = run_set(
        copy.deepcopy(raw), cfg, only={"a"}, use_cache=False, keep_payload=True
    )
    assert not fresh[0].cached and fresh[0].gui["code_str"]


def test_mechanism_parsed_once_across_solve_store_and_read_back(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The converter's ``create_solution`` is the only way a Solution is obtained.

    Asserts: with a host-style converter whose ``create_solution`` serves from its
    own cache and counts file parses, solving, writing the entry and reading it
    back (``keep_payload`` on a cached entry) parse the mechanism file once, and
    the process-wide ``load_solution`` cache is never filled behind the hook.
    """
    parsed: Dict[str, ct.Solution] = {}
    parses: List[str] = []

    class HostConverter(DualCanteraConverter):
        def create_solution(
            self, mech_name: str, *, kinetics: bool = True, transport: bool = False
        ) -> ct.Solution:
            path, _ = parse_mechanism_spec(mech_name)
            if path not in parsed:
                parses.append(path)
                parsed[path] = ct.Solution(path)
            return derive_solution(
                parsed[path],
                kinetics=kinetics,
                transport=transport,
                mechanism_path=path,
            )

    from boulder import ctutils

    monkeypatch.setattr(ctutils, "_PARSED_SOLUTIONS", {})
    run_set(_gri("a"), cfg, converter_cls=HostConverter)
    cached = run_set(_gri("a"), cfg, converter_cls=HostConverter, keep_payload=True)
    assert cached[0].cached and cached[0].gui["reactors_series"]
    assert parses == ["gri30.yaml"]
    assert ctutils._PARSED_SOLUTIONS == {}


def test_previous_entrys_network_is_released_before_the_next_build(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entry 1's network is not alive while entry 2 builds.

    Asserts: when each solve starts (before its network is built), the
    live-simulation singleton holds no network and a gc census finds no more
    ``ReactorNet`` than at the first solve (none left over from an earlier entry).
    """
    from boulder.simulation_worker import SimulationWorker

    seen: List[tuple[int, bool]] = []
    real = SimulationWorker.start_simulation

    def start(self: Any, *args: Any, **kwargs: Any) -> Any:
        gc.collect()
        nets = [o for o in gc.get_objects() if isinstance(o, ct.ReactorNet)]
        seen.append((len(nets), get_live_simulation().get_network() is None))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(SimulationWorker, "start_simulation", start)
    run_set(_gri("a", "b"), cfg)
    # Networks left by earlier tests in the process are the baseline (first solve).
    assert len(seen) == 3 and set(seen) == {(seen[0][0], True)}, seen


def test_outcome_carries_the_solve_wall_time(cfg: Path) -> None:
    """Asserts: a solved outcome has ``elapsed_s > 0`` without ``keep_payload``; a cached one 0."""
    solved = run_set(_gri("a"), cfg)
    assert solved[0].elapsed_s > 0 and solved[0].gui == {}
    assert run_set(_gri("a"), cfg)[0].elapsed_s == 0.0
