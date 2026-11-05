"""A run set of one entry writes into the run-set store, under a name.

``run_set`` is the one pipeline every entry point ends in, so a plain "Run
Simulation" and a "Run Sweep" of the same entry write the same thing: the entry
it was told to solve, with its fingerprints, its sources and its contributors.
The solve itself is stubbed (no Cantera): these tests pin what is *stored*.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Tuple
from unittest.mock import patch

import pytest

pytest.importorskip("h5py")

from boulder import cantera_converter, result_cache, sweep_runner  # noqa: E402
from boulder import scenario_store as store  # noqa: E402
from boulder.cantera_converter import BoulderPlugins  # noqa: E402
from boulder.runset import (  # noqa: E402
    BASELINE_SCENARIO_ID,
    resolve_store_dir,
    store_artifacts_dir,
)
from boulder.sweep_runner import (  # noqa: E402
    prepare_entry,
    run_set,
    scenario_fingerprint,
)

_RAW: Dict[str, Any] = {
    "metadata": {},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "network": [
        {
            "id": "r",
            "IdealGasReactor": {
                "volume": 1.0,
                "initial": {
                    "temperature": 300,
                    "pressure": 101325,
                    "composition": "N2:1",
                },
            },
        }
    ],
}

_PAYLOAD: Dict[str, Any] = {
    "status": "complete",
    "times": [0.0],
    "reactors_series": {},
    "reactor_reports": {},
    "connection_reports": {},
    "code_str": "# code",
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


class _Solved:
    """What a solved converter exposes to the store step; no Cantera involved."""

    def __init__(self, last_config: Dict[str, Any] | None = None) -> None:
        self._last_config = last_config

    def create_solution(self, mechanism: str, **_: Any) -> None:
        return None  # no template: the writer falls back to the plugin converter


def _solve(
    raw: Dict[str, Any],
    cfg: Path | None,
    *,
    only: Tuple[str, ...] = (BASELINE_SCENARIO_ID,),
    last_config: Dict[str, Any] | None = None,
) -> list:
    """Run *only* of *raw* through the pipeline with a stubbed solve."""
    with (
        patch.object(
            sweep_runner,
            "solve_scenario",
            return_value=(dict(_PAYLOAD), "gri30.yaml", _Solved(last_config)),
        ),
        # The stub is no real converter: the SimulationResult is not under test.
        patch(
            "boulder.simulation_result.make_simulation_result", return_value=object()
        ),
    ):
        return run_set(copy.deepcopy(raw), cfg, only=set(only))


def test_a_plain_run_writes_the_base_entry(cfg: Path) -> None:
    """No entry named -> the base entry, which is right for a single run."""
    _solve(_RAW, cfg)

    store_dir = resolve_store_dir({}, cfg)
    entries = store.list_entries(store_dir, store.config_identity(cfg))
    assert [e["id"] for e in entries] == [BASELINE_SCENARIO_ID]
    assert entries[0]["fingerprint"]


def test_the_solve_is_written_under_the_name_it_was_given(cfg: Path) -> None:
    """The entry id is the label; its order is its place in the run set."""
    raw = {**_RAW, "scenarios": {"first": {}, "short_residence_time": {}}}
    _solve(raw, cfg, only=("short_residence_time",))

    store_dir = resolve_store_dir({}, cfg)
    assert store_dir is not None
    attrs = store.entry_attrs(
        store_dir, "short_residence_time", store.config_identity(cfg)
    )
    assert attrs is not None
    assert attrs["label"] == "short_residence_time"
    assert attrs["order"] == 2  # BASELINE, first, then this one


def test_the_entry_answers_to_the_post_build_fingerprint_too(cfg: Path) -> None:
    """The frontend holds the post-build config; it must still see a hit.

    The staged solver enriches the network while building, so a config taken
    from the built network hashes differently from what was stored.
    """
    config, _, pre_fp = prepare_entry(copy.deepcopy(_RAW), BASELINE_SCENARIO_ID)
    enriched = copy.deepcopy(config)
    enriched["nodes"] = [
        *enriched["nodes"],
        {"id": "r_outlet", "type": "OutletSink", "properties": {}},
    ]
    post_fp = scenario_fingerprint(
        enriched,
        normalized=True,
        mechanism="gri30.yaml",
        resolve_mechanism=lambda name: name,
    )
    assert pre_fp != post_fp, "fixture no longer exercises the pre/post difference"

    _solve(_RAW, cfg, last_config=enriched)

    store_dir = resolve_store_dir({}, cfg)
    identity = store.config_identity(cfg)
    for fp in (pre_fp, post_fp):
        found = store.find_entry(store_dir, fp, identity) or {}
        assert found.get("id") == BASELINE_SCENARIO_ID
    # The canonical fingerprint -- the one a sweep compares -- is the pre-build one.
    assert store.fingerprints(store_dir, identity) == {BASELINE_SCENARIO_ID: pre_fp}


def test_contributors_write_under_the_entrys_own_artifacts_dir(cfg: Path) -> None:
    """Host artifacts are keyed by name, alongside the entry they belong to."""
    seen: Dict[str, Any] = {}

    class _Contributor(result_cache.CacheContributorPlugin):
        contributor_id = "test"

        def contribute(
            self,
            config: Any,
            converter: Any,
            simulation_result: Any,
            fingerprint: str,
            artifacts_dir: Path,
        ) -> None:
            seen["dir"] = artifacts_dir

    result_cache.get_cache_contributor_registry().contributors.append(_Contributor())
    raw = {**_RAW, "scenarios": {"hot": {}}}
    _solve(raw, cfg, only=("hot",))

    store_dir = resolve_store_dir({}, cfg)
    assert store_dir is not None
    assert seen["dir"] == store_artifacts_dir(store_dir, "hot")


def test_a_config_with_no_path_is_solved_but_not_stored(tmp_path: Path) -> None:
    """Nothing to key a store off: the entry is solved and returned, nothing is written."""
    (outcome,) = _solve(_RAW, None)

    assert outcome.sid == BASELINE_SCENARIO_ID
    assert outcome.cached is False
    assert list(tmp_path.iterdir()) == []


def test_store_failures_are_not_swallowed(cfg: Path) -> None:
    """A store write that fails fails the run: the entry would otherwise be silently lost."""
    with patch("boulder.scenario_store.write_entry", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            _solve(_RAW, cfg)


def test_an_unchanged_entry_is_served_from_the_store(cfg: Path) -> None:
    """A second run of the same entry solves nothing and says it was cached."""
    _solve(_RAW, cfg)
    with patch.object(
        sweep_runner, "solve_scenario", side_effect=AssertionError("re-solved")
    ):
        (outcome,) = run_set(
            copy.deepcopy(_RAW),
            cfg,
            only={BASELINE_SCENARIO_ID},
            keep_payload=True,
        )

    assert outcome.cached is True
    assert outcome.gui["times"] == [0.0]

    # `use_cache=False` re-solves even so (Force Run).
    with patch.object(
        sweep_runner,
        "solve_scenario",
        return_value=(dict(_PAYLOAD), "gri30.yaml", _Solved()),
    ):
        (forced,) = run_set(
            copy.deepcopy(_RAW), cfg, only={BASELINE_SCENARIO_ID}, use_cache=False
        )
    assert forced.cached is False


def test_an_unknown_entry_is_an_error(cfg: Path) -> None:
    """Asking for an entry the run set does not declare fails before any solve."""
    with pytest.raises(ValueError, match="Unknown scenario 'nope'"):
        _solve(_RAW, cfg, only=("nope",))


def test_a_plain_run_of_a_scenario_config_writes_BASELINE_not_BASE(cfg: Path) -> None:
    """The base's name must match what a sweep of the same config would use.

    With `scenarios:` declared, Run Sweep stored the base as `BASELINE` while Run
    Simulation once stored the identical result as `BASE`: one result, two names,
    which a single store makes impossible.
    """
    raw = {**_RAW, "scenarios": {"hot": {}, "cold": {}}}
    _solve(raw, cfg)

    ids = [
        e["id"]
        for e in store.list_entries(
            resolve_store_dir(raw, cfg), store.config_identity(cfg)
        )
    ]
    assert ids == [BASELINE_SCENARIO_ID], f"plain run stored the base as {ids}"


def test_a_global_sweep_config_still_has_a_base_run(cfg: Path) -> None:
    """A config whose run set is only sweep points (no unmodified base) can run its base."""
    raw = {
        **_RAW,
        "scenarios_sweep": {
            "T": {
                "path": "network[id=r].IdealGasReactor.initial.temperature",
                "values": [300, 350],
            }
        },
    }
    (outcome,) = _solve(raw, cfg)

    assert outcome.sid == BASELINE_SCENARIO_ID
