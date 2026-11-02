"""``--sweep --headless --no-cache`` reaches the sweep subprocess."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("h5py")

from boulder import cli  # noqa: E402

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


def _sweep(cfg: Path, *flags: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(cfg), "--sweep", "--headless", *flags])
    assert exc.value.code == 0


def test_headless_sweep_no_cache_resolves_everything(
    tmp_path: Path, monkeypatch, capfd
) -> None:
    """A second headless sweep reuses the store; with ``--no-cache`` it re-solves.

    The first run solves 1 scenario, the second reports 1 cached, and the third
    (``--no-cache``) reports 0 cached: the variable is set before the sweep
    subprocess starts.
    """
    monkeypatch.setenv("BOULDER_NO_CACHE", "")  # restored on teardown
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_YAML, encoding="utf-8")
    _sweep(cfg)
    assert "0 cached, 1 solved" in capfd.readouterr().out
    _sweep(cfg)
    assert "1 cached, 0 solved" in capfd.readouterr().out
    _sweep(cfg, "--no-cache")
    assert "0 cached, 1 solved" in capfd.readouterr().out
