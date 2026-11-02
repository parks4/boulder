"""One converter-selection rule for the runner, the GUI startup and the sweep."""

from __future__ import annotations

import shutil
from pathlib import Path

import cantera as ct
import pytest

pytest.importorskip("h5py")

from boulder import cantera_converter, sweep_runner  # noqa: E402
from boulder.cantera_converter import (  # noqa: E402
    BoulderPlugins,
    DualCanteraConverter,
    select_converter_class,
)
from boulder.runner import BoulderRunner  # noqa: E402

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


class _Rewriting(DualCanteraConverter):
    """Converter whose resolved mechanism differs from the bare name."""

    mech_dir = ""

    def resolve_mechanism(self, name: str) -> str:
        return str(Path(self.mech_dir) / name)


class _Other(DualCanteraConverter):
    pass


def test_rule_is_runner_then_plugin_then_default() -> None:
    """The helper picks the runner's class, else the plugin's, else the default."""
    plugins = BoulderPlugins()
    assert select_converter_class(None, plugins) is DualCanteraConverter
    plugins.converter_class = _Rewriting
    assert select_converter_class(None, plugins) is _Rewriting
    assert select_converter_class(_Other, plugins) is _Other


def test_headless_run_then_sweep_share_the_plugin_converter(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A headless run without ``--runner`` solves with the plugin's converter.

    With a plugin converter registered, the run's fingerprint equals the sweep's,
    so the sweep reports "1 cached, 0 solved".
    """

    shutil.copy(Path(ct.__file__).parent / "data" / "gri30.yaml", tmp_path)
    plugins = BoulderPlugins()
    plugins.converter_class = type("C", (_Rewriting,), {"mech_dir": str(tmp_path)})
    monkeypatch.setattr(cantera_converter, "_PLUGIN_CACHE", plugins)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_YAML, encoding="utf-8")
    runner = BoulderRunner.from_yaml(str(cfg))
    runner.plugins = plugins
    runner.run_headless(end_time=0.01, dt=0.005)
    capsys.readouterr()
    sweep_runner.run(cfg)
    assert "1 cached, 0 solved" in capsys.readouterr().out
