"""A plain solve writes into the run-set store, under a name.

This is the seam that makes "Run Simulation" and "Run Sweep" one mechanism: the
worker no longer keeps a private content-addressed cache, it writes the entry it
was told it is solving. A single run is simply the N=1 entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

pytest.importorskip("h5py")

from boulder import scenario_store as store  # noqa: E402
from boulder.runset import (  # noqa: E402
    BASE_SCENARIO_ID,
    resolve_store_dir,
    store_artifacts_dir,
)
from boulder.simulation_worker import SimulationWorker  # noqa: E402

_CONFIG: Dict[str, Any] = {
    "metadata": {},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "nodes": [{"id": "r", "type": "IdealGasReactor", "properties": {}}],
    "connections": [],
}


class _StubConverter:
    """Enough surface for `_persist_to_cache`; no Cantera involved."""

    def __init__(self, config_path: Path, contributors: Any = ()) -> None:
        self.mechanism = "gri30.yaml"
        self._download_config_path = str(config_path)

        class _Plugins:
            cache_contributors = contributors

        self.plugins = _Plugins()

    def resolve_mechanism(self, name: str) -> str:
        return name


def _persist(
    worker: SimulationWorker,
    converter: _StubConverter,
    *,
    post_build_config: Dict[str, Any] | None = None,
) -> None:
    """Drive the worker's persist step with a stubbed SimulationResult."""
    config = post_build_config if post_build_config is not None else dict(_CONFIG)
    with patch(
        "boulder.simulation_result.make_simulation_result", return_value=object()
    ):
        worker._persist_to_cache(
            converter,
            config,
            {"is_complete": True},
            {},
            {},
            "# code",
            pre_build_config=dict(_CONFIG),
        )


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    path = tmp_path / "model.yaml"
    path.write_text("metadata: {}\n", encoding="utf-8")
    return path


def test_a_plain_solve_writes_the_base_entry(cfg: Path) -> None:
    """No run identity set -> the base entry, which is right for a single run."""
    worker = SimulationWorker()
    _persist(worker, _StubConverter(cfg))

    store_dir = resolve_store_dir({}, cfg)
    identity = store.config_identity(cfg)
    entries = store.list_entries(store_dir, identity)
    assert [e["id"] for e in entries] == [BASE_SCENARIO_ID]
    assert entries[0]["fingerprint"]


def test_the_solve_is_written_under_the_name_it_was_given(cfg: Path) -> None:
    worker = SimulationWorker()
    worker.set_run_identity("short_residence_time", label="Short", order=2)
    _persist(worker, _StubConverter(cfg))

    store_dir = resolve_store_dir({}, cfg)
    assert store_dir is not None
    attrs = store.entry_attrs(
        store_dir, "short_residence_time", store.config_identity(cfg)
    )
    assert attrs is not None
    assert attrs["label"] == "Short"
    assert attrs["order"] == 2


def test_the_entry_answers_to_the_post_build_fingerprint_too(cfg: Path) -> None:
    """The frontend holds the post-build config; it must still see a hit.

    Without this a plain Run Simulation would re-solve on every click: the
    staged solver enriches the network while building, so what the browser
    sends back afterwards hashes differently from what was stored.
    """
    from boulder.result_cache import compute_fingerprint

    enriched = dict(_CONFIG)
    enriched["nodes"] = [
        *_CONFIG["nodes"],
        {"id": "r_outlet", "type": "OutletSink", "properties": {}},
    ]

    worker = SimulationWorker()
    _persist(worker, _StubConverter(cfg), post_build_config=enriched)

    store_dir = resolve_store_dir({}, cfg)
    identity = store.config_identity(cfg)
    pre_fp = compute_fingerprint(dict(_CONFIG), mechanism="gri30.yaml")
    post_fp = compute_fingerprint(enriched, mechanism="gri30.yaml")
    assert pre_fp != post_fp, "fixture no longer exercises the pre/post difference"

    assert store.is_current(store_dir, BASE_SCENARIO_ID, pre_fp, identity) is True
    assert store.is_current(store_dir, BASE_SCENARIO_ID, post_fp, identity) is True
    # The canonical fingerprint -- the one a sweep compares -- is the pre-build one.
    assert store.fingerprints(store_dir, identity) == {BASE_SCENARIO_ID: pre_fp}


def test_contributors_write_under_the_entrys_own_artifacts_dir(cfg: Path) -> None:
    """Host artifacts are keyed by name, alongside the entry they belong to."""
    seen: Dict[str, Any] = {}

    class _Contributor:
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

    worker = SimulationWorker()
    worker.set_run_identity("hot")
    _persist(worker, _StubConverter(cfg, contributors=[_Contributor()]))

    store_dir = resolve_store_dir({}, cfg)
    assert store_dir is not None
    assert seen["dir"] == store_artifacts_dir(store_dir, "hot")


def test_a_config_with_no_path_is_skipped_quietly(tmp_path: Path) -> None:
    """Nothing to key a store off; must not raise."""
    worker = SimulationWorker()
    converter = _StubConverter(tmp_path / "x.yaml")
    converter._download_config_path = None  # type: ignore[assignment]
    _persist(worker, converter)  # no exception


def test_persist_failures_never_propagate(cfg: Path) -> None:
    """A cache write must never turn a good solve into a failed request."""
    worker = SimulationWorker()
    with patch("boulder.scenario_store.write_entry", side_effect=OSError("disk full")):
        _persist(worker, _StubConverter(cfg))  # swallowed, logged


def test_the_entry_is_stored_before_completion_is_announced(cfg: Path) -> None:
    """`is_complete` must not go true until the result is in the store.

    The frontend reacts to completion immediately -- re-listing GUI actions,
    which asks the store whether a result exists. Storing after announcing
    raced that, and the client used to hide the race behind a 3-second
    re-fetch timer. This pins the ordering so the timer stays deleted.
    """
    worker = SimulationWorker()
    complete_at_persist_time: list[bool] = []

    def _spy(*args: Any, **kwargs: Any) -> None:
        complete_at_persist_time.append(worker.progress.is_complete)

    class _Net:
        pass

    conv = _StubConverter(cfg)
    conv.reactors = {}  # type: ignore[attr-defined]
    conv.build_network = lambda *a, **k: _Net()  # type: ignore[attr-defined]
    conv.run_streaming_simulation = lambda *a, **k: (  # type: ignore[attr-defined]
        {"time": [0.0], "reactors": {}},
        "# code",
    )

    with (
        patch.object(worker, "_persist_to_cache", side_effect=_spy),
        patch("boulder.simulation_worker.generate_reactor_reports", return_value={}),
        patch("boulder.simulation_worker.generate_connection_reports", return_value={}),
        # Imported inside the function, so patch it at its source module.
        patch("boulder.live_simulation.update_live_simulation"),
    ):
        worker._run_simulation(conv, dict(_CONFIG), 1.0, 0.1)

    assert complete_at_persist_time == [False], (
        "the result was stored after completion was announced -- a client that "
        "reacts to `is_complete` can see a finished run with no stored entry"
    )
    assert worker.progress.is_complete is True


def test_a_plain_solve_of_a_scenario_config_writes_BASELINE_not_BASE(
    tmp_path: Path,
) -> None:
    """The base's name must match what a sweep of the same config would use.

    Found in the GUI: with `scenarios:` declared, Run Sweep stored the base as
    `BASELINE` while Run Simulation stored the identical result as `BASE`. The
    pane then showed a phantom `BASE` row and left the authored `BASELINE` row
    reading "Not computed yet" -- one result, two names, which is exactly what
    a single store is supposed to make impossible.
    """
    from boulder.runset import BASELINE_SCENARIO_ID, base_entry_id, expand_scenarios

    raw = {**_CONFIG, "scenarios": {"hot": {}, "cold": {}}}
    cfg = tmp_path / "with_scenarios.yaml"
    cfg.write_text("metadata: {}\n", encoding="utf-8")

    # The two paths agree, and agree on the name the sweep actually emits.
    assert base_entry_id(raw) == BASELINE_SCENARIO_ID
    assert expand_scenarios(raw)[0][0] == BASELINE_SCENARIO_ID

    worker = SimulationWorker()
    worker._raw_config = raw
    _persist(worker, _StubConverter(cfg))

    ids = [
        e["id"]
        for e in store.list_entries(
            resolve_store_dir(raw, cfg), store.config_identity(cfg)
        )
    ]
    assert ids == [BASELINE_SCENARIO_ID], f"plain solve stored the base as {ids}"


def test_a_sweep_only_config_keeps_the_plain_base_name(tmp_path: Path) -> None:
    """A global `sweep:` emits no unmodified-base entry, so the base stays BASE.

    Guards the over-broad version of the rule: treating `sweep:` like
    `scenarios:` renamed every sweep point's `BASE__<axis>` prefix too.
    """
    from boulder.runset import BASE_SCENARIO_ID, base_entry_id

    raw = {
        **_CONFIG,
        "sweep": {"T": {"path": "nodes[id=r].properties.T", "values": [1, 2]}},
    }
    assert base_entry_id(raw) == BASE_SCENARIO_ID
