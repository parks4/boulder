"""The result store's correctness guarantees.

Moving from a content-addressed cache to a name-addressed one removes the
collision-immunity hashing gave for free: two configs both named ``case.yaml``
can land in one directory. Serving one config's results for another would be
unacceptable; re-solving because they invalidate each other is merely wasteful.
These tests pin that distinction, plus the two write-ordering invariants
described in :mod:`boulder.scenario_store`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

h5py = pytest.importorskip("h5py")

from boulder import scenario_store as store  # noqa: E402
from boulder.runset import (  # noqa: E402
    resolve_store_dir,
    store_artifacts_dir,
    store_entry_name,
    store_entry_path,
)

_PAYLOAD: Dict[str, Any] = {
    "status": "complete",
    "is_complete": True,
    "times": [0.0, 1.0],
    "reactors_series": {},
}


def _write(
    store_dir: Path, sid: str, identity: str, fingerprint: str = "fp", **kw: Any
) -> Path:
    return store.write_entry(
        store_dir,
        sid,
        gui_payload=dict(_PAYLOAD),
        mechanism="gri30.yaml",
        fingerprint=fingerprint,
        identity=identity,
        **kw,
    )


# --------------------------------------------------------------------------- #
# Same-named configs must never share results
# --------------------------------------------------------------------------- #


def test_same_stem_configs_get_separate_directories(tmp_path: Path) -> None:
    """The default layout keeps two `case.yaml` files apart by construction."""
    a = tmp_path / "a" / "case.yaml"
    b = tmp_path / "b" / "case.yaml"
    for cfg in (a, b):
        cfg.parent.mkdir(parents=True)
        cfg.write_text("metadata: {}\n", encoding="utf-8")

    dir_a = resolve_store_dir({}, a)
    dir_b = resolve_store_dir({}, b)
    assert dir_a is not None and dir_b is not None
    assert dir_a != dir_b


def test_shared_cache_dir_still_separates_same_stem_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """$BOULDER_CACHE_DIR points every config at one root -- names must not collide."""
    shared = tmp_path / "shared-cache"
    monkeypatch.setenv("BOULDER_CACHE_DIR", str(shared))

    a = tmp_path / "a" / "case.yaml"
    b = tmp_path / "b" / "case.yaml"
    for cfg in (a, b):
        cfg.parent.mkdir(parents=True)
        cfg.write_text("metadata: {}\n", encoding="utf-8")

    dir_a = resolve_store_dir({}, a)
    dir_b = resolve_store_dir({}, b)
    assert dir_a != dir_b, "same-stem configs shared a directory under a shared root"
    assert shared in dir_a.parents and shared in dir_b.parents


def test_neither_config_ever_reads_the_others_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: solve both, and neither sees the other's entry."""
    monkeypatch.setenv("BOULDER_CACHE_DIR", str(tmp_path / "shared"))
    a = tmp_path / "a" / "case.yaml"
    b = tmp_path / "b" / "case.yaml"
    for cfg in (a, b):
        cfg.parent.mkdir(parents=True)
        cfg.write_text("metadata: {}\n", encoding="utf-8")

    dir_a, dir_b = resolve_store_dir({}, a), resolve_store_dir({}, b)
    id_a, id_b = store.config_identity(a), store.config_identity(b)

    _write(dir_a, "BASELINE", id_a, fingerprint="fp-a")
    _write(dir_b, "BASELINE", id_b, fingerprint="fp-b")

    assert store.fingerprints(dir_a, id_a) == {"BASELINE": "fp-a"}
    assert store.fingerprints(dir_b, id_b) == {"BASELINE": "fp-b"}


def test_a_forced_collision_rebuilds_rather_than_serving_the_wrong_result(
    tmp_path: Path,
) -> None:
    """The identity stamp is the backstop when a path collision is forced.

    Wrong results served: unacceptable. Mutual invalidation: acceptable.
    """
    shared = tmp_path / "forced"
    _write(shared, "BASELINE", store.config_identity(tmp_path / "a" / "case.yaml"))

    other = store.config_identity(tmp_path / "b" / "case.yaml")
    assert store.entry_attrs(shared, "BASELINE", other) is None
    assert store.read_entry(shared, "BASELINE", other) is None
    assert store.list_entries(shared, other) == []
    # ...and no fingerprint, so the other config re-solves instead.
    assert store.fingerprints(shared, other) == {}


def test_a_moved_config_does_not_reuse_its_old_entries(tmp_path: Path) -> None:
    """Identity is the config path, so relocating it invalidates -- by design."""
    d = tmp_path / "store"
    _write(d, "BASELINE", store.config_identity(tmp_path / "old" / "case.yaml"))
    moved = store.config_identity(tmp_path / "new" / "case.yaml")
    assert store.entry_attrs(d, "BASELINE", moved) is None


# --------------------------------------------------------------------------- #
# Never serve a half-written or stale-format entry
# --------------------------------------------------------------------------- #


def test_an_entry_without_a_fingerprint_reads_as_not_computed(tmp_path: Path) -> None:
    """A solve that died mid-write must not look like a valid result."""
    d = tmp_path / "store"
    path = _write(d, "BASELINE", "id")
    with h5py.File(str(path), "a") as handle:
        del handle.attrs["fingerprint"]  # simulate an interrupted write

    assert store.entry_attrs(d, "BASELINE", "id") is None
    assert store.read_entry(d, "BASELINE", "id") is None
    assert store.list_entries(d, "id") == []


def test_a_stale_store_version_is_rebuilt_not_misread(tmp_path: Path) -> None:
    d = tmp_path / "store"
    path = _write(d, "BASELINE", "id")
    with h5py.File(str(path), "a") as handle:
        handle.attrs["store_version"] = store.STORE_VERSION + 1

    assert store.entry_attrs(d, "BASELINE", "id") is None


def test_a_corrupt_file_is_skipped_rather_than_raising(tmp_path: Path) -> None:
    """A reader must degrade to 'not available', never propagate an OSError."""
    d = tmp_path / "store"
    d.mkdir(parents=True)
    (d / "BASELINE.h5").write_bytes(b"this is not HDF5")

    assert store.entry_attrs(d, "BASELINE", "id") is None
    assert store.read_entry(d, "BASELINE", "id") is None
    assert store.list_entries(d, "id") == []


# --------------------------------------------------------------------------- #
# Round trip, listing, lifecycle
# --------------------------------------------------------------------------- #


def test_round_trip_payload_and_attrs(tmp_path: Path) -> None:
    d = tmp_path / "store"
    _write(d, "hot", "id", fingerprint="fp1", label="Hot case", order=2)

    attrs = store.entry_attrs(d, "hot", "id")
    assert attrs is not None
    assert attrs["fingerprint"] == "fp1"
    assert attrs["label"] == "Hot case"
    assert attrs["order"] == 2
    assert attrs["computed_at"] > 0

    payload = store.read_entry(d, "hot", "id")
    assert payload is not None
    assert payload["times"] == [0.0, 1.0]


def test_entries_are_listed_in_run_set_order(tmp_path: Path) -> None:
    d = tmp_path / "store"
    _write(d, "second", "id", order=1)
    _write(d, "first", "id", order=0)
    assert [e["id"] for e in store.list_entries(d, "id")] == ["first", "second"]


def test_kpi_attrs_survive_and_are_distinguishable_from_bookkeeping(
    tmp_path: Path,
) -> None:
    """Host KPIs and auto-walked inputs must reach the Sweep Results plot."""
    d = tmp_path / "store"
    _write(d, "hot", "id", extra_attrs={"in.feed.temperature": 300.0, "eta": 0.42})

    attrs = store.entry_attrs(d, "hot", "id")
    assert attrs is not None
    kpis = {
        k: v for k, v in attrs.items() if k not in store.NON_KPI_ATTRS and k != "id"
    }
    assert kpis == {"in.feed.temperature": 300.0, "eta": 0.42}


def test_delete_entry_removes_the_file_and_its_artifacts(tmp_path: Path) -> None:
    d = tmp_path / "store"
    _write(d, "hot", "id")
    art = store_artifacts_dir(d, "hot")
    art.mkdir(parents=True)
    (art / "bundle.json").write_text("{}", encoding="utf-8")

    assert store.delete_entry(d, "hot") is True
    assert not store_entry_path(d, "hot").exists()
    assert not art.exists(), "artifacts outlived their entry"
    assert store.delete_entry(d, "hot") is False


def test_prune_removes_only_entries_that_left_the_run_set(tmp_path: Path) -> None:
    d = tmp_path / "store"
    _write(d, "keep", "id")
    _write(d, "renamed_away", "id")
    art = store_artifacts_dir(d, "renamed_away")
    art.mkdir(parents=True)

    removed = store.prune_entries(d, {"keep", "brand_new"})
    assert removed == ["renamed_away"]
    assert store_entry_path(d, "keep").is_file()
    assert not art.exists()


def test_clear_removes_entries_and_artifacts(tmp_path: Path) -> None:
    d = tmp_path / "store"
    _write(d, "hot", "id")
    store_artifacts_dir(d, "hot").mkdir(parents=True)

    assert store.clear(d) is True
    assert not d.exists()
    assert store.clear(d) is False


# --------------------------------------------------------------------------- #
# Staleness: solve, or reuse?
# --------------------------------------------------------------------------- #


def test_is_current_only_for_the_matching_fingerprint(tmp_path: Path) -> None:
    d = tmp_path / "store"
    _write(d, "hot", "id", fingerprint="fp-now")

    assert store.is_current(d, "hot", "fp-now", "id") is True
    assert store.is_current(d, "hot", "fp-edited", "id") is False
    assert store.is_current(d, "absent", "fp-now", "id") is False
    assert store.is_current(None, "hot", "fp-now", "id") is False


def test_the_same_entry_answers_to_its_post_build_fingerprint_too(
    tmp_path: Path,
) -> None:
    """One solve, two valid descriptions of it.

    The staged solver enriches the network while building, so the config the
    frontend holds afterwards hashes differently from the pre-build config a
    sweep derives. Both must find this entry current, or a plain Run Simulation
    would re-solve on every click.
    """
    d = tmp_path / "store"
    _write(d, "hot", "id", fingerprint="fp-pre", alt_fingerprints=("fp-post",))

    assert store.is_current(d, "hot", "fp-pre", "id") is True
    assert store.is_current(d, "hot", "fp-post", "id") is True
    assert store.is_current(d, "hot", "fp-unrelated", "id") is False
    # The canonical fingerprint is what a sweep compares against.
    assert store.fingerprints(d, "id") == {"hot": "fp-pre"}


def test_an_alt_equal_to_the_canonical_one_is_not_recorded(tmp_path: Path) -> None:
    """No redundant attr when the build did not change the config."""
    d = tmp_path / "store"
    _write(d, "hot", "id", fingerprint="fp", alt_fingerprints=("fp",))
    attrs = store.entry_attrs(d, "hot", "id")
    assert "alt_fingerprints" not in attrs


def test_a_foreign_config_is_never_current(tmp_path: Path) -> None:
    """The identity guard also gates staleness, not just reads."""
    d = tmp_path / "store"
    _write(d, "hot", store.config_identity(tmp_path / "a.yaml"), fingerprint="fp")
    other = store.config_identity(tmp_path / "b.yaml")
    assert store.is_current(d, "hot", "fp", other) is False


# --------------------------------------------------------------------------- #
# Ids from YAML are not filename-safe
# --------------------------------------------------------------------------- #


def test_a_slash_in_an_id_cannot_become_a_nested_path(tmp_path: Path) -> None:
    """`/` would otherwise be an HDF5/filesystem separator, not part of the name."""
    name = store_entry_name("a/b")
    assert "/" not in name and "\\" not in name

    d = tmp_path / "store"
    _write(d, "a/b", "id")
    assert store_entry_path(d, "a/b").parent == d
    assert store.entry_attrs(d, "a/b", "id") is not None


def test_ids_that_sanitise_alike_still_get_separate_files(tmp_path: Path) -> None:
    """Sanitising alone would silently merge distinct scenarios into one entry."""
    assert store_entry_name("a/b") != store_entry_name("a_b")

    d = tmp_path / "store"
    _write(d, "a/b", "id", fingerprint="fp-slash")
    _write(d, "a_b", "id", fingerprint="fp-underscore")

    assert store.entry_attrs(d, "a/b", "id")["fingerprint"] == "fp-slash"
    assert store.entry_attrs(d, "a_b", "id")["fingerprint"] == "fp-underscore"


def test_a_windows_reserved_id_is_still_writable(tmp_path: Path) -> None:
    assert store_entry_name("CON") != "CON"
    d = tmp_path / "store"
    _write(d, "CON", "id")
    assert store.entry_attrs(d, "CON", "id") is not None


def test_an_ordinary_id_is_used_verbatim() -> None:
    """The common case stays readable in the directory listing."""
    assert store_entry_name("BASELINE") == "BASELINE"
    assert store_entry_name("short_residence-time.2") == "short_residence-time.2"


def test_the_api_publishes_the_non_kpi_attr_set(tmp_path: Path) -> None:
    """The plot's exclusion list must come from the store, not a frontend copy.

    A hand-mirrored list in TypeScript drifted the moment the store gained an
    attr: `store_version` was offered as a selectable Sweep Results axis. The
    server therefore publishes the set and the frontend consumes it.
    """
    import pytest as _pytest

    _pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from boulder import scenario_store
    from boulder.api.main import create_app

    cfg = tmp_path / "model.yaml"
    cfg.write_text("metadata: {}\n", encoding="utf-8")

    app = create_app()
    with TestClient(app) as client:
        app.state.preloaded_config_path = str(cfg)
        published = client.get("/api/scenarios").json()["non_kpi_keys"]

    assert set(published) == set(scenario_store.NON_KPI_ATTRS)
    # The two that actually bit: bookkeeping ints a naive numeric scan plots.
    assert "store_version" in published
    assert "schema_version" in published
