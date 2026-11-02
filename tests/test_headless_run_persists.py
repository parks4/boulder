"""``BoulderRunner.run_headless`` (``--headless --run``) records its solve.

It used to write no store entry and run no cache contributor, unlike the GUI
worker and the sweep runner, so a host recording solves through contributors
saw nothing from a headless single run.  ``--download`` alone only writes code.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("h5py")

from boulder import (  # noqa: E402
    cantera_converter,
    cli,
    result_cache,
    scenario_store,
    sweep_runner,
)
from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter  # noqa: E402
from boulder.config import normalize_config, validate_config  # noqa: E402
from boulder.result_cache import CacheContributorPlugin  # noqa: E402
from boulder.runner import BoulderRunner  # noqa: E402
from boulder.runset import resolve_store_dir  # noqa: E402
from boulder.sweep_runner import (  # noqa: E402
    converter_mechanism_resolver,
    scenario_fingerprint,
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


def _headless(cfg: Path, rec: _Recorder) -> BoulderRunner:
    plugins = BoulderPlugins()
    plugins.cache_contributors = [rec]
    runner = BoulderRunner.from_yaml(str(cfg))
    runner.plugins = plugins
    return runner.run_headless(end_time=0.01, dt=0.005)


def _entry(cfg: Path) -> Dict[str, Any]:
    store_dir = resolve_store_dir(BoulderRunner.load(str(cfg)), str(cfg))
    assert store_dir is not None
    identity = scenario_store.config_identity(cfg)
    (listed,) = scenario_store.list_entries(store_dir, identity)
    return {"id": listed["id"]}


def _fresh_plugins(monkeypatch, contributors: list) -> None:
    """Make ``get_plugins()`` rediscover, with *contributors* in the registry."""
    monkeypatch.setattr(cantera_converter, "_PLUGIN_CACHE", None)
    registry = result_cache.get_cache_contributor_registry()
    monkeypatch.setattr(registry, "contributors", contributors)


def test_headless_run_then_sweep_is_a_cache_hit(tmp_path, capsys) -> None:
    """A headless run is a cache hit for the sweep and the GUI startup lookup.

    The contributor fires once; the sweep then reports "1 cached, 0 solved" and
    the GUI startup fingerprint finds the entry.
    """
    cfg = _cfg(tmp_path, "cli")
    rec = _Recorder()
    _headless(cfg, rec)
    assert len(rec.fingerprints) == 1
    capsys.readouterr()
    sweep_runner.run(cfg)
    assert "1 cached, 0 solved" in capsys.readouterr().out

    raw = BoulderRunner.load(str(cfg))
    fp = scenario_fingerprint(
        validate_config(normalize_config(copy.deepcopy(raw))),
        normalized=True,
        resolve_mechanism=converter_mechanism_resolver(DualCanteraConverter),
    )
    assert fp == rec.fingerprints[0]
    store_dir = resolve_store_dir(raw, str(cfg))
    identity = scenario_store.config_identity(cfg)
    assert scenario_store.load_matching(store_dir, fp, identity)


def test_download_without_run_persists_nothing(tmp_path, monkeypatch) -> None:
    """``--headless --download`` alone writes no store entry, calls no contributor.

    With ``--run`` it does both.
    """
    rec = _Recorder()
    _fresh_plugins(monkeypatch, [rec])
    cfg = _cfg(tmp_path, "cli")
    out = tmp_path / "gen.py"
    cli.main([str(cfg), "--headless", "--download", str(out)])
    assert out.exists()
    assert rec.fingerprints == []
    assert not (cfg.parent / ".boulder-cache").exists()
    cli.main([str(cfg), "--headless", "--run"])
    assert len(rec.fingerprints) == 1


def test_plugin_registered_contributor_fires_once(tmp_path, monkeypatch) -> None:
    """A contributor registered by a ``BOULDER_PLUGINS`` module fires once."""
    (tmp_path / "hp_plugin_mod.py").write_text(
        "from boulder.result_cache import (\n"
        "    CacheContributorPlugin, register_cache_contributor)\n"
        "CALLS = []\n"
        "class C(CacheContributorPlugin):\n"
        "    contributor_id = 'hp_plugin'\n"
        "    def contribute(self, config, converter, simulation_result, fp, adir):\n"
        "        CALLS.append(fp)\n"
        "def register_plugins(plugins):\n"
        "    register_cache_contributor(C())\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("BOULDER_PLUGINS", "hp_plugin_mod")
    _fresh_plugins(monkeypatch, [])
    cfg = _cfg(tmp_path, "cli")
    BoulderRunner.from_yaml(str(cfg)).run_headless(end_time=0.01, dt=0.005)
    mod = sys.modules["hp_plugin_mod"]
    monkeypatch.delitem(sys.modules, "hp_plugin_mod")
    assert len(mod.CALLS) == 1


def test_a_raising_contributor_does_not_fail_the_run(tmp_path) -> None:
    """The run completes and its entry is stored although the contributor raises."""
    cfg = _cfg(tmp_path, "cli")
    rec = _Recorder(raises=True)
    runner = _headless(cfg, rec)
    assert runner.result is not None
    assert len(rec.fingerprints) == 1
    assert _entry(cfg)["id"]
