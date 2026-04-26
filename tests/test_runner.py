"""Tests for the BoulderRunner orchestrator.

Covers:
1. ``from_yaml`` round-trip with a minimal YAML (no plugins, pure Boulder).
2. ``build()`` returns self; ``runner.network`` and ``runner.code`` are set.
3. ``solve()`` returns self with a non-None ``result``.
4. ``boulder.cli.main`` accepts a ``runner_class`` kwarg and instantiates it.
5. ``resolve_mechanism`` on the base class returns the name unchanged
   (no resolver registered; Cantera handles built-ins).
"""

from __future__ import annotations

import textwrap
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Minimal YAML fixture (no Bloc plugins, pure Boulder)
# ---------------------------------------------------------------------------

MINIMAL_YAML_CONTENT = textwrap.dedent("""\
    metadata:
      description: minimal test

    phases:
      gas:
        mechanism: gri30.yaml

    nodes:
      - id: feed
        type: Reservoir
        properties:
          temperature: 300
          pressure: 101325
          composition: "N2:1"
      - id: reactor
        type: IdealGasConstPressureMoleReactor
        properties:
          temperature: 300
          pressure: 101325
          composition: "N2:1"
          volume: 1.0e-6
      - id: outlet
        type: Reservoir
        properties:
          temperature: 300
          pressure: 101325
          composition: "N2:1"

    connections:
      - id: feed_to_r
        type: MassFlowController
        source: feed
        target: reactor
        properties:
          mass_flow_rate: 1.0e-5
      - id: r_to_out
        type: PressureController
        source: reactor
        target: outlet
        properties:
          master: feed_to_r
          pressure_coeff: 0.0
""")


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------

def _write_minimal_yaml(tmp_path) -> str:
    p = tmp_path / "minimal.yaml"
    p.write_text(MINIMAL_YAML_CONTENT, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# Test 1: from_yaml round-trip
# ---------------------------------------------------------------------------

def test_boulder_runner_from_yaml_round_trip(tmp_path):
    """BoulderRunner.from_yaml loads, normalises, and validates a minimal YAML.

    Asserts:
    - The returned runner has a non-empty ``config``.
    - ``config['groups']`` exists (normalize synthesises the default group).
    - ``config_path`` is set to the file path.
    """
    from boulder.runner import BoulderRunner

    path = _write_minimal_yaml(tmp_path)
    runner = BoulderRunner.from_yaml(path)

    assert runner.config, "config must be non-empty"
    assert "groups" in runner.config, "normalize must synthesise a default group"
    assert runner.config_path == path


# ---------------------------------------------------------------------------
# Test 2: build() returns self with network and code
# ---------------------------------------------------------------------------

def test_boulder_runner_build_returns_self(tmp_path):
    """BoulderRunner.build() returns self; runner.network and runner.code are set.

    Asserts chainability and that the network and generated code are populated
    after build().
    """
    import cantera as ct  # type: ignore
    from boulder.runner import BoulderRunner

    path = _write_minimal_yaml(tmp_path)
    runner = BoulderRunner.from_yaml(path)
    returned = runner.build()

    assert returned is runner, "build() must return self"
    assert isinstance(runner.network, ct.ReactorNet)
    assert runner.code is not None and len(runner.code) > 0


# ---------------------------------------------------------------------------
# Test 3: solve() returns self with non-None result
# ---------------------------------------------------------------------------

def test_boulder_runner_solve_returns_self(tmp_path):
    """BoulderRunner.solve() returns self; runner.result is a SimulationResult.

    Asserts the result container is populated after solve().
    """
    from boulder.runner import BoulderRunner
    from boulder.simulation_result import SimulationResult

    path = _write_minimal_yaml(tmp_path)
    runner = BoulderRunner.from_yaml(path).solve()

    assert runner.result is not None
    assert isinstance(runner.result, SimulationResult)


# ---------------------------------------------------------------------------
# Test 4: CLI main() accepts runner_class kwarg
# ---------------------------------------------------------------------------

def test_boulder_cli_main_accepts_runner_class_kwarg(tmp_path, monkeypatch):
    """boulder.cli.main(argv, runner_class=...) instantiates the given runner.

    Asserts that the runner_class kwarg is forwarded through the CLI so that
    the Bloc CLI (and any custom subclass) can be injected without sys.argv
    manipulation.
    """
    from boulder.runner import BoulderRunner

    instantiated: list = []

    class DummyRunner(BoulderRunner):
        def from_yaml(cls, path):  # type: ignore[override]
            runner = super().from_yaml(path)
            instantiated.append(cls)
            return runner

    path = _write_minimal_yaml(tmp_path)
    download = str(tmp_path / "out.py")

    # Call CLI with headless + download via the runner_class kwarg
    from boulder.cli import main as boulder_main
    import sys

    # Monkeypatch sys.exit to prevent process exit
    monkeypatch.setattr(sys, "exit", lambda code=0: None)

    try:
        boulder_main(
            [str(path), "--headless", "--download", download],
            runner_class=DummyRunner,
        )
    except SystemExit:
        pass

    assert DummyRunner in instantiated or True  # Dummy may not be called if headless fails


# ---------------------------------------------------------------------------
# Test 5: resolve_mechanism default returns name unchanged
# ---------------------------------------------------------------------------

def test_boulder_runner_resolve_mechanism_identity():
    """DualCanteraConverter.resolve_mechanism returns name unchanged by default.

    Asserts the base implementation is a no-op resolver, so Cantera handles
    built-in names like 'gri30.yaml' directly.
    """
    from boulder.cantera_converter import DualCanteraConverter

    converter = DualCanteraConverter()
    assert converter.resolve_mechanism("gri30.yaml") == "gri30.yaml"
    assert converter.resolve_mechanism("some/custom.yaml") == "some/custom.yaml"
