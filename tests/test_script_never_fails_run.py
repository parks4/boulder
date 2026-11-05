"""Writing the downloadable script never fails a solve.

The script embeds the run's resolved YAML and loads it through the solving
runner class (``normalize`` / ``validate``), so any config the solver accepts
can be written.  When the script cannot reproduce the run (a runner class that
cannot be imported, a config that cannot be dumped to YAML) it is still
written, and its first executable line raises a clear ``RuntimeError``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

pytest.importorskip("h5py")

from boulder import cantera_converter, cli  # noqa: E402
from boulder.runner import BoulderRunner  # noqa: E402

_CONFIG = """\
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_grid
    grid: {{start: 0.0, stop: 0.01, dt: 0.005}}
    {solver_extra}
{top_extra}
network:
  - id: feed
    Reservoir: {{temperature: 300, pressure: 101325, composition: "N2:1"}}
  - id: reactor
    IdealGasReactor:
      volume: 1.0
      initial: {{temperature: 300, pressure: 101325, composition: "N2:1"}}
  - id: outlet
    Reservoir: {{temperature: 300, pressure: 101325, composition: "N2:1"}}
  - id: inlet
    MassFlowController: {{mass_flow_rate: 0.01}}
    source: feed
    target: reactor
  - id: valve
    Valve: {{valve_coeff: 1.0}}
    source: reactor
    target: outlet
"""

_HOST = '''\
import numpy as np
from boulder.runner import BoulderRunner


class NumpyRunner(BoulderRunner):
    """A host whose normalize leaves numpy floats in the config."""

    @classmethod
    def normalize(cls, cfg):
        cfg = super().normalize(cfg)
        grid = cfg["settings"]["solver"]["grid"]
        grid["stop"] = np.float64(grid["stop"])
        grid["dt"] = np.float64(grid["dt"])
        return cfg
'''

_DUMP = """
import json
json.dump(
    {rid: [r.phase.T, r.phase.P] for rid, r in converter.reactors.items()},
    open({out!r}, "w"),  # replaced with the path
)
"""


def _config(solver_extra: str = "", top_extra: str = "") -> str:
    return _CONFIG.format(solver_extra=solver_extra, top_extra=top_extra)


def _states(runner: BoulderRunner) -> Dict[str, Any]:
    assert runner.converter is not None
    return {rid: [r.phase.T, r.phase.P] for rid, r in runner.converter.reactors.items()}


def _run_script(root: Path, script: Path, out: Optional[Path] = None):
    """Run *script* in a subprocess with a clean temp dir and this checkout's Boulder."""
    if out is not None:
        script.write_text(
            script.read_text("utf-8") + _DUMP.replace("{out!r}", repr(str(out))),
            encoding="utf-8",
        )
    boulder_root = str(Path(cantera_converter.__file__).parent.parent)
    env = dict(os.environ, TMP=str(root), TEMP=str(root), TMPDIR=str(root))
    env["PYTHONPATH"] = os.pathsep.join([str(root), boulder_root])
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(root),
        env=env,
    )


_CASES = {
    "date": _config(top_extra="metadata:\n  name: x\n  date: 2026-11-05"),
    "inf": _config(solver_extra="max_time_step: .inf"),
    "numpy": _config(),
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_valid_config_solves_and_its_script_reproduces_the_states(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config with a date, an infinite step or numpy floats solves, and so does its script.

    Asserts the solve completes (it used to fail while writing the script),
    that the script written by ``--headless --download`` exits 0 when run in a
    subprocess, and that it leaves the reactor T and P of the solve.
    """
    (tmp_path / "host_runner.py").write_text(_HOST, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    from host_runner import NumpyRunner

    runner_cls = NumpyRunner if case == "numpy" else BoulderRunner
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CASES[case], encoding="utf-8")
    script = tmp_path / "downloaded.py"

    runner = runner_cls.from_yaml(str(cfg)).build()
    cli.main(
        [str(cfg), "--headless", "--download", str(script)], runner_class=runner_cls
    )

    out = tmp_path / "states.json"
    run = _run_script(tmp_path, script, out)
    assert run.returncode == 0, run.stderr[-3000:]
    got = json.loads(out.read_text("utf-8"))
    for rid, (temp, pres) in _states(runner).items():
        assert got[rid] == pytest.approx([temp, pres], rel=1e-9), rid


def test_a_runner_that_cannot_be_imported_gives_a_script_that_raises(
    tmp_path: Path,
) -> None:
    """A runner defined in a function: the solve completes, the script says why.

    Asserts the solve is not failed, the script has no ``<locals>`` import, and
    running it fails with a ``RuntimeError`` that names the runner class.
    """

    class LocalRunner(BoulderRunner):
        pass

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_config(), encoding="utf-8")
    script = tmp_path / "downloaded.py"

    runner = LocalRunner.from_yaml(str(cfg))
    runner.run_headless(download_path=str(script))

    assert runner.network is not None
    text = script.read_text("utf-8")
    compile(text, "downloaded.py", "exec")  # no `from ...<locals>... import`
    run = _run_script(tmp_path, script)
    assert run.returncode != 0
    assert "RuntimeError" in run.stderr and "LocalRunner" in run.stderr


def test_a_config_that_cannot_be_dumped_gives_a_script_that_raises(
    tmp_path: Path,
) -> None:
    """A prepared config holding an object YAML cannot dump: solve ok, script raises.

    Asserts ``BoulderRunner(config)`` (no source text to embed) still solves
    with a numpy float in its config and that the script's run raises a
    ``RuntimeError`` naming the cause.
    """
    import numpy as np

    from boulder.config import normalize_config, validate_config
    from boulder.runset import load_yaml_with_inheritance

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_config(), encoding="utf-8")
    config = validate_config(normalize_config(load_yaml_with_inheritance(cfg)))
    config["settings"]["solver"]["grid"]["stop"] = np.float64(0.01)
    script = tmp_path / "downloaded.py"

    runner = BoulderRunner(config)
    runner.run_headless(download_path=str(script))

    assert runner.network is not None
    run = _run_script(tmp_path, script)
    assert run.returncode != 0
    assert "RuntimeError" in run.stderr and "YAML" in run.stderr


def test_script_embeds_the_resolved_yaml_and_the_runner_route(tmp_path: Path) -> None:
    """The script carries the YAML text and goes through normalize/validate."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_config(), encoding="utf-8")
    script = tmp_path / "downloaded.py"
    BoulderRunner.from_yaml(str(cfg)).run_headless(download_path=str(script))
    text = script.read_text("utf-8")
    assert "mechanism: gri30.yaml" in text
    assert "BoulderRunner.normalize" in text
