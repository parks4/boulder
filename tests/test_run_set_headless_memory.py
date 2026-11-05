"""A headless ``run_set`` keeps no per-entry payload, and memory stays flat over a sweep.

``EntryOutcome.gui`` carries the GUI worker payload, and a cached entry reads it
back from the store. Only the GUI routes (and ``run --download``) look at it, so
``run_set`` fills it on request (``keep_payload``). Without that, every entry's
payload stayed alive until the sweep ended: peak memory grew with entry count.
"""

from __future__ import annotations

import copy
import gc
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("h5py")

from boulder import cantera_converter, result_cache, scenario_store  # noqa: E402
from boulder.cantera_converter import BoulderPlugins  # noqa: E402
from boulder.sweep_runner import run_set  # noqa: E402

_RAW: Dict[str, Any] = {
    "metadata": {},
    "phases": {"gas": {"mechanism": "example_data/n-hexane-NUIG-2015.yaml"}},
    "network": [
        {
            "id": "r",
            "IdealGasReactor": {
                "volume": 1.0,
                "initial": {
                    "temperature": 1000,
                    "pressure": 101325,
                    "composition": "NC6H14:0.0216, O2:0.2056, N2:0.7728",
                },
            },
        }
    ],
    "settings": {"end_time": 1e-3, "dt": 1e-6},
    "scenarios": {f"s{i}": {} for i in range(5)},
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
    gri = {"gas": {"mechanism": "gri30.yaml"}}  # small: three solves here
    raw = copy.deepcopy({**_RAW, "phases": gri, "scenarios": {"a": {}}})
    raw["network"][0]["IdealGasReactor"]["initial"]["composition"] = (
        "CH4:1, O2:2, N2:7.5"
    )
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


@pytest.mark.slow
def test_peak_memory_does_not_grow_with_entry_count(cfg: Path) -> None:
    """Memory stays flat over a sweep.

    Asserts: on a 1100-species mechanism, RSS at the start of each of the 6
    solved entries, after the first two (allocator warm-up), grows by less than
    20 MB: nothing accumulates per entry.
    """
    psutil = pytest.importorskip("psutil")
    proc = psutil.Process()
    rss: List[float] = []

    def on_entry(*_: Any) -> None:
        gc.collect()
        rss.append(proc.memory_info().rss / 1e6)

    outcomes = run_set(copy.deepcopy(_RAW), cfg, on_entry=on_entry)
    assert len(rss) == len(outcomes) >= 5 and not any(o.cached for o in outcomes)
    # Measured: flat within 3 MB here; with every payload kept it grew ~40 MB.
    assert max(rss[2:]) - rss[2] < 20, rss
