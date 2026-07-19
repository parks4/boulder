"""Unit tests for :mod:`boulder.sweep_runner` collection-store cache primitives."""

from __future__ import annotations

from pathlib import Path

import h5py

from boulder.sweep_runner import existing_fingerprints, prune_stale_groups


def _make_store(path: Path, groups: dict) -> None:
    """Create a collection store with ``{group_id: fingerprint | None}``."""
    with h5py.File(str(path), "w") as handle:
        for sid, fingerprint in groups.items():
            group = handle.create_group(sid)
            group.create_dataset("payload_json", data="{}")
            if fingerprint:
                group.attrs["fingerprint"] = fingerprint


def test_existing_fingerprints_reads_groups_with_payload(tmp_path: Path):
    store = tmp_path / "map_scenarios.h5"
    _make_store(store, {"a": "fp-a", "b": "fp-b", "unfingerprinted": None})
    assert existing_fingerprints(store) == {"a": "fp-a", "b": "fp-b"}


def test_existing_fingerprints_empty_for_missing_store(tmp_path: Path):
    assert existing_fingerprints(tmp_path / "nope.h5") == {}


def test_existing_fingerprints_ignores_groups_without_payload(tmp_path: Path):
    store = tmp_path / "map_scenarios.h5"
    with h5py.File(str(store), "w") as handle:
        handle.create_group("half_written").attrs["fingerprint"] = "fp"
    assert existing_fingerprints(store) == {}


def test_prune_stale_groups_removes_ids_that_left_the_run_set(tmp_path: Path):
    store = tmp_path / "map_scenarios.h5"
    _make_store(store, {"keep": "fp-1", "renamed_away": "fp-2"})
    stale = prune_stale_groups(store, {"keep", "brand_new"})
    assert stale == ["renamed_away"]
    with h5py.File(str(store), "r") as handle:
        assert list(handle.keys()) == ["keep"]
