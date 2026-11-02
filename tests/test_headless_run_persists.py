"""``BoulderRunner.run_headless`` (``--headless --run``) records its solve.

It used to write no store entry and run no cache contributor, unlike the GUI
worker and the sweep runner, so a host recording solves through contributors
saw nothing from a headless single run.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("h5py")

from boulder import scenario_store  # noqa: E402
from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter  # noqa: E402
from boulder.config import normalize_config, validate_config  # noqa: E402
from boulder.result_cache import CacheContributorPlugin  # noqa: E402
from boulder.runner import BoulderRunner  # noqa: E402
from boulder.runset import resolve_store_dir  # noqa: E402
from boulder.simulation_worker import (  # noqa: E402
    SimulationWorker,
    generate_connection_reports,
    generate_reactor_reports,
)

_YAML = """\
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

# Times and paths that legitimately differ between two solves of the same file.
_VOLATILE = {"computed_at", "solved_at", "elapsed_time", "identity", "config_identity"}


class _Recorder(CacheContributorPlugin):
    def __init__(self, raises: bool = False) -> None:
        self.fingerprints: List[str] = []
        self.raises = raises

    @property
    def contributor_id(self) -> str:
        return "test_recorder"

    def contribute(self, config, converter, simulation_result, fingerprint, adir):
        self.fingerprints.append(fingerprint)
        if self.raises:
            raise RuntimeError("contributor failure")


def _cfg(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    cfg = folder / "config.yaml"
    cfg.write_text(_YAML, encoding="utf-8")
    return cfg


def _plugins(rec: _Recorder) -> BoulderPlugins:
    plugins = BoulderPlugins()
    plugins.cache_contributors = [rec]
    return plugins


def _headless(cfg: Path, rec: _Recorder) -> BoulderRunner:
    runner = BoulderRunner.from_yaml(str(cfg))
    runner.plugins = _plugins(rec)
    return runner.run_headless(end_time=0.01, dt=0.005)


def _entry(cfg: Path) -> Dict[str, Any]:
    store_dir = resolve_store_dir(BoulderRunner.load(str(cfg)), str(cfg))
    assert store_dir is not None
    identity = scenario_store.config_identity(cfg)
    (listed,) = scenario_store.list_entries(store_dir, identity)
    attrs = scenario_store.entry_attrs(store_dir, listed["id"], identity)
    return {"id": listed["id"], "attrs": attrs}


def _gui_solve(cfg: Path, rec: _Recorder) -> None:
    """Persist the same file the way the GUI worker's solve does."""
    raw = BoulderRunner.load(str(cfg))
    config = validate_config(normalize_config(copy.deepcopy(raw)))
    converter = DualCanteraConverter(plugins=_plugins(rec))
    converter._download_config_path = str(cfg)
    pre = {
        **config,
        "nodes": copy.deepcopy(config["nodes"]),
        "connections": copy.deepcopy(config["connections"]),
    }
    converter.build_network(config)
    results, code = converter.run_streaming_simulation(0.01, 0.005, config=config)
    worker = SimulationWorker()
    worker.set_run_identity(
        None, raw_config=raw, source=scenario_store.build_source(raw, cfg)
    )
    worker.progress.times = results["time"]
    worker.progress.reactors_series = results["reactors"]
    worker._persist_to_cache(
        converter,
        config,
        results,
        generate_reactor_reports(converter, results),
        generate_connection_reports(converter),
        code,
        pre_build_config=pre,
    )


def test_headless_run_fires_contributor_with_the_gui_fingerprint(tmp_path) -> None:
    """One contributor call per headless run, with the fingerprint a GUI solve gets."""
    rec_cli, rec_gui = _Recorder(), _Recorder()
    _headless(_cfg(tmp_path, "cli"), rec_cli)
    _gui_solve(_cfg(tmp_path, "gui"), rec_gui)
    assert len(rec_cli.fingerprints) == 1
    assert rec_cli.fingerprints == rec_gui.fingerprints


def test_headless_run_writes_the_entry_the_worker_writes(tmp_path) -> None:
    """The headless store entry has the same id and non-volatile attrs as the worker's."""
    cli, gui = _cfg(tmp_path, "cli"), _cfg(tmp_path, "gui")
    _headless(cli, _Recorder())
    _gui_solve(gui, _Recorder())
    a, b = _entry(cli), _entry(gui)
    assert a["id"] == b["id"]
    keep = set(a["attrs"]) - _VOLATILE
    assert keep == set(b["attrs"]) - _VOLATILE
    assert {k: a["attrs"][k] for k in keep} == {k: b["attrs"][k] for k in keep}
    assert a["attrs"]["fingerprint"]


def test_a_raising_contributor_does_not_fail_the_run(tmp_path) -> None:
    """The run completes and its entry is stored although the contributor raises."""
    cfg = _cfg(tmp_path, "cli")
    rec = _Recorder(raises=True)
    runner = _headless(cfg, rec)
    assert runner.result is not None
    assert len(rec.fingerprints) == 1
    assert _entry(cfg)["id"]
