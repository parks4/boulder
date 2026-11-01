"""The result store records which run-set definition produced each entry.

An entry kept the fingerprint of its config but not the definition behind it,
and not even its scenario id (``list_entries`` fell back to the sanitised file
stem). These tests solve real runs on a neutral gri30 network (``feed`` /
``reactor`` / ``outlet``) and read the definition, the leaf text, the ``from:``
chain and the display name back, through every path that writes an entry.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from boulder import result_cache, scenario_store, sweep_runner
from boulder.runset import (
    inheritance_chain,
    load_yaml_with_inheritance,
    store_artifacts_dir,
)

_BASE_YAML = """\
phases:
  gas:
    mechanism: gri30.yaml
settings:
  end_time: 0.01
  dt: 0.005
network:
  - id: feed
    Reservoir:
      temperature: 300
      pressure: 101325
      composition: "N2:1"
  - id: reactor
    IdealGasReactor:
      volume: 1.0
      initial:
        temperature: 300
        pressure: 101325
        composition: "N2:1"
  - id: outlet
    Reservoir:
      temperature: 300
      pressure: 101325
      composition: "N2:1"
  - id: inlet
    MassFlowController:
      mass_flow_rate: 0.01
    source: feed
    target: reactor
  - id: valve
    Valve:
      valve_coeff: 1.0
    source: reactor
    target: outlet
"""

_FEED_T = "network[id=feed].Reservoir.temperature"

_LEAF_YAML = f"""\
from: base.yaml
scenarios:
  hot:
    network:
      - id: feed
        Reservoir:
          temperature: 350
scenarios_sweep:
  T:
    path: "{_FEED_T}"
    values: [300, 350]
"""

_CHAIN_LEAF_YAML = f"""\
from: base.yaml
scenarios_sweep:
  for:
    parameter: "{_FEED_T}"
    values: [300, 350]
"""


def _write(tmp_path: Path, leaf: str = _LEAF_YAML) -> Path:
    (tmp_path / "base.yaml").write_text(_BASE_YAML, encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(leaf, encoding="utf-8")
    return cfg


def _entries(store_dir: Path) -> List[Dict[str, Any]]:
    return scenario_store.list_entries(store_dir, identity="")


class _Reader(result_cache.CacheContributorPlugin):
    """Reads the source of the entry it is called for, from its artifacts dir."""

    def __init__(self) -> None:
        self.sources: List[Any] = []

    @property
    def contributor_id(self) -> str:
        return "source_reader"

    def contribute(
        self, config, converter, simulation_result, fingerprint, artifacts_dir
    ):
        self.sources.append(scenario_store.read_source_for_artifacts_dir(artifacts_dir))


def test_inheritance_chain_lists_the_parents_nearest_first(tmp_path: Path) -> None:
    """``inheritance_chain`` returns each resolved ``from:`` parent, nearest first."""
    (tmp_path / "grand.yaml").write_text(_BASE_YAML, encoding="utf-8")
    (tmp_path / "mid.yaml").write_text("from: grand.yaml\n", encoding="utf-8")
    leaf = tmp_path / "leaf.yaml"
    leaf.write_text("from: mid.yaml\n", encoding="utf-8")

    assert inheritance_chain(leaf) == [
        (tmp_path / "mid.yaml").resolve(),
        (tmp_path / "grand.yaml").resolve(),
    ]
    assert inheritance_chain(tmp_path / "grand.yaml") == []


def test_headless_sweep_entries_keep_their_ids_and_one_source(tmp_path: Path) -> None:
    """Headless entries keep their raw ids (even with ``=``) and share one source.

    The source holds the definition with ``scenarios:`` and
    ``scenarios_sweep:`` intact, the leaf text verbatim, the ``from:`` chain
    relative to the leaf, and the file name.
    """
    cfg = _write(tmp_path)

    store_dir = sweep_runner.run(cfg)

    entries = _entries(store_dir)
    ids = {e["id"] for e in entries}
    assert {"BASELINE", "hot", "BASELINE__T=300", "BASELINE__T=350"} <= ids
    assert len({e["source_sha256"] for e in entries}) == 1

    src = scenario_store.read_source(store_dir, "BASELINE__T=350")
    assert src is not None
    assert "scenarios_sweep" in src.definition and "hot" in src.definition
    assert "from:" not in src.definition  # parents merged
    assert "feed" in src.definition  # the parent's network is in
    assert src.leaf_text == _LEAF_YAML
    assert src.chain == ("base.yaml",)
    assert src.display_name == "config.yaml"
    assert (store_dir / "sources" / f"{entries[0]['source_sha256']}.yaml").is_file()


def test_a_contributor_can_read_the_source_of_its_entry(
    tmp_path: Path, monkeypatch
) -> None:
    """A cache contributor reads its entry's source through its artifacts dir."""
    reader = _Reader()
    monkeypatch.setattr(
        result_cache._cache_contributor_registry, "contributors", [reader]
    )

    sweep_runner.run(_write(tmp_path))

    assert reader.sources, "contributor never called"
    assert all(s is not None and s.leaf_text == _LEAF_YAML for s in reader.sources)


def test_a_chain_records_its_source_on_every_point(tmp_path: Path) -> None:
    """A ``for:`` chain records its one run-set definition on every point.

    Its points depend on earlier solves, so they cannot be recomputed.
    """
    store_dir = sweep_runner.run(_write(tmp_path, _CHAIN_LEAF_YAML))

    entries = _entries(store_dir)
    assert len(entries) == 2
    assert len({e["source_sha256"] for e in entries}) == 1
    src = scenario_store.read_source(store_dir, entries[0]["id"])
    assert src is not None and "for" in src.definition


def test_an_entry_without_a_source_reads_as_none(tmp_path: Path) -> None:
    """An entry written without a source (or before this feature) reads ``None``."""
    store_dir = tmp_path / "store"
    scenario_store.write_entry(
        store_dir,
        "T=1",
        gui_payload={"status": "complete"},
        mechanism="gri30.yaml",
        fingerprint="f" * 64,
        identity="",
    )

    assert scenario_store.read_source(store_dir, "T=1") is None
    assert [e["id"] for e in _entries(store_dir)] == ["T=1"]


def test_the_source_never_reaches_the_fingerprint(tmp_path: Path) -> None:
    """A sweep entry's stored fingerprint is ``compute_fingerprint`` of its config.

    The config is the fixture's base scenario, normalised and hashed with no
    source involved: recording the source does not change the cache key.
    """
    from boulder.cantera_converter import get_plugins
    from boulder.config import normalize_config
    from boulder.runset import RunSetCursor, iter_run_set

    cfg = _write(tmp_path)
    expanded = dict(iter_run_set(load_yaml_with_inheritance(cfg), RunSetCursor()))
    plugins = get_plugins()
    expected = result_cache.compute_fingerprint(
        normalize_config(copy.deepcopy(expanded["hot"]), plugins=plugins),
        # The identity the run hashes: the mechanism as the converter resolves it.
        mechanism=sweep_runner._default_resolve_mechanism(plugins)("gri30.yaml"),
    )

    store_dir = sweep_runner.run(cfg)

    hot = next(e for e in _entries(store_dir) if e["id"] == "hot")
    assert hot["source_sha256"]
    assert hot["fingerprint"] == expected


# --------------------------------------------------------------------------- #
# GUI paths
# --------------------------------------------------------------------------- #

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _gui(tmp_path: Path):
    from boulder.api.main import create_app
    from boulder.runset import load_yaml_with_inheritance

    cfg = _write(tmp_path)
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    app.state.preloaded_filename = cfg.name
    app.state.preloaded_yaml = cfg.read_text(encoding="utf-8")
    app.state.preloaded_raw = load_yaml_with_inheritance(cfg)
    return client, app, cfg


def _run_gui_sweep(client: TestClient, app: Any, scenarios: Dict[str, Any]) -> None:
    resp = client.post("/api/sweep/run", json={"scenarios": scenarios})
    assert resp.status_code == 200, resp.text
    deadline = time.time() + 120
    while app.state.sweep_job.get("status") not in ("done", "error"):
        assert time.time() < deadline, "sweep did not finish"
        time.sleep(0.05)
    assert app.state.sweep_job.get("status") == "done", app.state.sweep_job


def _hot(temperature: float) -> Dict[str, Any]:
    node = {"id": "feed", "Reservoir": {"temperature": temperature}}
    return {"hot": {"network": [node]}}


def test_gui_edit_then_rerun_one_scenario_gives_two_sources(tmp_path: Path) -> None:
    """A browser edit then a one-scenario re-run leaves two sources.

    File-backed session: it leaves two sources, each entry pointing to its own,
    and the user's file untouched on disk.
    """
    from boulder.runset import resolve_store_dir

    client, app, cfg = _gui(tmp_path)
    on_disk = cfg.read_bytes()
    try:
        _run_gui_sweep(client, app, _hot(350))
        store_dir = resolve_store_dir(app.state.preloaded_raw, str(cfg))
        assert store_dir is not None
        first = {e["id"]: e["source_sha256"] for e in _entries(store_dir)}
        assert set(first) == {"BASELINE", "hot", "BASELINE__T=300", "BASELINE__T=350"}
        assert len(set(first.values())) == 1

        # The browser edits the YAML (in memory only) and re-runs: BASELINE is
        # unchanged and cached, "hot" differs and is re-solved.
        app.state.preloaded_yaml = _LEAF_YAML + "# edited in the browser\n"
        _run_gui_sweep(client, app, _hot(360))

        second = {e["id"]: e["source_sha256"] for e in _entries(store_dir)}
        assert {k: v for k, v in second.items() if k != "hot"} == {
            k: v for k, v in first.items() if k != "hot"
        }
        assert second["hot"] != first["hot"]
        old = scenario_store.read_source(store_dir, "BASELINE")
        new = scenario_store.read_source(store_dir, "hot")
        assert old is not None and new is not None
        assert old.leaf_text == _LEAF_YAML
        assert new.leaf_text.endswith("# edited in the browser\n")
        assert new.display_name == "config.yaml"
        assert len(list((store_dir / "sources").glob("*.yaml"))) == 2
        assert cfg.read_bytes() == on_disk
    finally:
        client.__exit__(None, None, None)


def test_an_uploaded_config_records_its_original_file_name(tmp_path: Path) -> None:
    """An uploaded config records its original file name.

    An upload is solved from a private temp file; the source keeps the name
    the user's file had.
    """
    from boulder.api.main import create_app
    from boulder.runset import resolve_store_dir

    app = create_app()
    with TestClient(app) as client:
        simple = _BASE_YAML + "scenarios:\n  hot:\n    settings:\n      dt: 0.0025\n"
        resp = client.post(
            "/api/configs/upload",
            files={"file": ("my_model.yaml", simple.encode("utf-8"), "text/yaml")},
        )
        assert resp.status_code == 200, resp.text
        _run_gui_sweep(client, app, {"hot": {"settings": {"dt": 0.0025}}})

        store_dir = resolve_store_dir(
            app.state.preloaded_raw, app.state.preloaded_config_path
        )
        assert store_dir is not None
        src = scenario_store.read_source(store_dir, "hot")
        assert src is not None
        assert src.display_name == "my_model.yaml"
        assert src.leaf_text == simple
        assert src.chain == ()
        assert store_artifacts_dir(store_dir, "hot").parent.name == "artifacts"


def test_a_single_run_records_its_source(tmp_path: Path) -> None:
    """A plain run records its source and its raw id.

    The worker's persist step stores the session's definition, the browser's
    leaf text and the loaded file's name.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from boulder.runset import resolve_store_dir
    from boulder.simulation_worker import SimulationWorker

    cfg = _write(tmp_path)
    raw = {"network": [{"id": "feed"}], "scenarios": {"a=1": {}}}
    converter = SimpleNamespace(
        mechanism="gri30.yaml",
        _download_config_path=str(cfg),
        plugins=SimpleNamespace(cache_contributors=[]),
        resolve_mechanism=lambda name: name,
    )
    worker = SimulationWorker()
    source = scenario_store.build_source(
        raw, cfg, leaf_text="edited: true\n", display_name="my_model.yaml"
    )
    worker.set_run_identity("a=1", raw_config=raw, source=source)

    with patch(
        "boulder.simulation_result.make_simulation_result", return_value=object()
    ):
        worker._persist_to_cache(
            converter, {}, {"is_complete": True}, {}, {}, "# code", pre_build_config={}
        )

    store_dir = resolve_store_dir(raw, cfg)
    assert store_dir is not None
    assert [e["id"] for e in _entries(store_dir)] == ["a=1"]
    src = scenario_store.read_source(store_dir, "a=1")
    assert src is not None
    assert "a=1" in src.definition
    assert src.leaf_text == "edited: true\n"
    assert src.display_name == "my_model.yaml"
    # The browser's text has no `from:`, so no chain, whatever the file says.
    assert src.chain == ()


def test_the_chain_follows_the_leaf_text_given(tmp_path: Path) -> None:
    """With ``leaf_text``, the ``from:`` chain is read from that text.

    The text names ``other.yaml`` (next to the leaf) while the file on disk names
    ``base.yaml``: the chain is ``("other.yaml",)``.
    """
    cfg = _write(tmp_path)
    (tmp_path / "other.yaml").write_text(_BASE_YAML, encoding="utf-8")

    src = scenario_store.build_source({}, cfg, leaf_text="from: other.yaml\n")

    assert src.chain == ("other.yaml",)
    assert scenario_store.build_source({}, cfg).chain == ("base.yaml",)


def test_a_cyclic_from_chain_raises_instead_of_recursing(tmp_path: Path) -> None:
    """``load_yaml_with_inheritance`` raises ``ValueError`` on a ``from:`` cycle."""
    (tmp_path / "a.yaml").write_text("from: b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("from: a.yaml\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cycle"):
        load_yaml_with_inheritance(tmp_path / "a.yaml")


def _run_config(app: Any) -> Dict[str, Any]:
    """Return the session base config, normalised as the frontend submits it."""
    from boulder.cantera_converter import get_plugins
    from boulder.config import normalize_config

    return normalize_config(
        copy.deepcopy(app.state.preloaded_raw), plugins=get_plugins()
    )


def _start_run(client: TestClient, app: Any, during_solve) -> Dict[str, Any]:
    """POST a plain run; *during_solve* fires once the solve has started."""
    from boulder.simulation_worker import SimulationWorker

    original = SimulationWorker.start_simulation

    def start(self, *args, **kwargs):
        original(self, *args, **kwargs)
        during_solve()

    SimulationWorker.start_simulation = start  # type: ignore[method-assign]
    try:
        resp = client.post("/api/simulations", json={"config": _run_config(app)})
    finally:
        SimulationWorker.start_simulation = original  # type: ignore[method-assign]
    assert resp.status_code == 200, resp.text
    from boulder.runset import resolve_store_dir

    store_dir = resolve_store_dir(
        app.state.preloaded_raw, app.state.preloaded_config_path
    )
    assert store_dir is not None
    deadline = time.time() + 120
    while not _entries(store_dir):
        assert time.time() < deadline, "the solved entry was never written"
        time.sleep(0.05)
    return {"store_dir": store_dir}


def test_a_run_keeps_the_source_it_started_with_when_the_file_vanishes(
    tmp_path: Path,
) -> None:
    """The leaf and its parent disappearing mid-solve still leaves the entry.

    The source is captured when the run starts, so the solved entry is written
    with that source instead of being lost to a failed re-read after the solve.
    """
    client, app, cfg = _gui(tmp_path)
    try:

        def vanish() -> None:
            cfg.unlink()
            (tmp_path / "base.yaml").unlink()

        store_dir = _start_run(client, app, vanish)["store_dir"]
        src = scenario_store.read_source(store_dir, _entries(store_dir)[0]["id"])
        assert src is not None
        assert src.leaf_text == _LEAF_YAML
        assert src.chain == ("base.yaml",)
    finally:
        client.__exit__(None, None, None)


def test_a_run_keeps_the_leaf_text_it_started_with(tmp_path: Path) -> None:
    """A live edit of ``preloaded_yaml`` mid-solve does not reach the stored source."""
    client, app, _cfg = _gui(tmp_path)
    try:

        def edit() -> None:
            app.state.preloaded_yaml = "edited: later\n"

        store_dir = _start_run(client, app, edit)["store_dir"]
        src = scenario_store.read_source(store_dir, _entries(store_dir)[0]["id"])
        assert src is not None
        assert src.leaf_text == _LEAF_YAML
    finally:
        client.__exit__(None, None, None)


def test_a_run_whose_source_cannot_be_built_fails_before_the_solve(
    tmp_path: Path,
) -> None:
    """A missing parent file makes the run request fail (500) before any solve."""
    client, app, _cfg = _gui(tmp_path)
    try:
        (tmp_path / "base.yaml").unlink()
        resp = client.post("/api/simulations", json={"config": _run_config(app)})
        assert resp.status_code == 500
        assert "base.yaml" in resp.text
    finally:
        client.__exit__(None, None, None)
