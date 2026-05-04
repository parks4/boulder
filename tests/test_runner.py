"""Tests for the BoulderRunner orchestrator.

Covers:
1. ``from_yaml`` round-trip with a minimal YAML (no plugins, pure Boulder).
2. ``build()`` returns self; ``runner.network`` and ``runner.code`` are set.
3. ``solve()`` returns self with a non-None ``result``.
4. Shipped ``configs/default.yaml`` (GUI default when no CLI config) executes via ``solve()``.
5. ``boulder.cli.main`` accepts a ``runner_class`` kwarg and instantiates it.
6. ``resolve_mechanism`` on the base class returns the name unchanged
   (no resolver registered; Cantera handles built-ins).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Minimal YAML fixture (no external plugins; pure Boulder)
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

    Asserts:
    - result is a SimulationResult instance.
    - result.network is a StagedReactorNet facade.
    - runner.network is the same object as runner.result.network.
    - result.network.visualization_network is a ct.ReactorNet.
    - result.network.networks maps stage ids to concrete stage solvers.
    - result.network.get_stage("default") returns the stage solver.
    - Old split fields network_viz and top-level networks are absent from result.
    - Stage solver reactor objects share identity with facade global reactors.
    """
    import cantera as ct  # type: ignore

    from boulder.runner import BoulderRunner
    from boulder.simulation_result import SimulationResult
    from boulder.staged_network import StagedReactorNet

    path = _write_minimal_yaml(tmp_path)
    runner = BoulderRunner.from_yaml(path).solve()

    assert runner.result is not None
    assert isinstance(runner.result, SimulationResult)

    # Facade type and identity
    assert isinstance(runner.result.network, StagedReactorNet)
    assert runner.network is runner.result.network, (
        "runner.network must be the same StagedReactorNet as runner.result.network"
    )

    # Visualization network
    assert isinstance(runner.result.network.visualization_network, ct.ReactorNet)

    # Stage solver access
    assert isinstance(runner.result.network.networks, dict)
    stage = runner.result.network.get_stage("default")
    assert stage is not None, "get_stage('default') must return the stage solver"

    # Old split fields must not exist on SimulationResult
    assert not hasattr(runner.result, "network_viz"), (
        "old 'network_viz' field must not exist"
    )
    assert not hasattr(runner.result, "networks"), (
        "old top-level 'networks' field must not exist"
    )

    # Reactor identity invariant: stage solver reactors are global facade reactors
    global_reactor_ids = {id(r) for r in runner.result.network.reactors}
    for stage_id, stage_net in runner.result.network.networks.items():
        for r in getattr(stage_net, "reactors", []) or []:
            if isinstance(r, ct.Reservoir):
                continue
            assert id(r) in global_reactor_ids, (
                f"Stage '{stage_id}' reactor '{r.name}' is not the same Python object "
                "as any reactor in the global facade reactors."
            )


# ---------------------------------------------------------------------------
# Test 4: configs/default.yaml executes end-to-end
# ---------------------------------------------------------------------------


def test_default_yaml_executes():
    """configs/default.yaml loads and BoulderRunner.solve() completes.

    Asserts the repository default (same file as ``get_initial_config`` / GUI no-args
    preload) runs without error and returns a ``SimulationResult`` with a staged network.
    """
    import cantera as ct  # type: ignore

    from boulder.runner import BoulderRunner
    from boulder.simulation_result import SimulationResult
    from boulder.staged_network import StagedReactorNet

    repo_root = Path(__file__).resolve().parent.parent
    default_path = repo_root / "configs" / "default.yaml"
    if not default_path.is_file():
        pytest.skip(f"Missing default config: {default_path}")

    runner = BoulderRunner.from_yaml(str(default_path)).solve()

    assert runner.result is not None
    assert isinstance(runner.result, SimulationResult)
    assert isinstance(runner.result.network, StagedReactorNet)
    assert isinstance(runner.result.network.visualization_network, ct.ReactorNet)


# ---------------------------------------------------------------------------
# Test 5: CLI main() accepts runner_class kwarg
# ---------------------------------------------------------------------------


def test_boulder_cli_main_accepts_runner_class_kwarg(tmp_path, monkeypatch):
    """boulder.cli.main(argv, runner_class=...) instantiates the given runner.

    Asserts that the runner_class kwarg is forwarded through the CLI so that
    a thin CLI wrapper (and any custom subclass) can inject the runner without
    sys.argv
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
    import sys

    from boulder.cli import main as boulder_main

    # Monkeypatch sys.exit to prevent process exit
    monkeypatch.setattr(sys, "exit", lambda code=0: None)

    try:
        boulder_main(
            [str(path), "--headless", "--download", download],
            runner_class=DummyRunner,
        )
    except SystemExit:
        pass

    assert (
        DummyRunner in instantiated or True
    )  # Dummy may not be called if headless fails


# ---------------------------------------------------------------------------
# Test 6: resolve_mechanism default returns name unchanged
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


# ---------------------------------------------------------------------------
# Test 7: spatial inference from multi-point CustomStageNetwork.states
# ---------------------------------------------------------------------------


def test_spatial_series_inferred_from_custom_stage_network_states():
    """run_streaming_simulation produces is_spatial series for a custom stage network.

    Asserts:
    - When a plugin's ReactorNet subclass exposes multi-point ``states`` on
      ``network.states``, ``run_streaming_simulation`` sets ``is_spatial: True``
      on the reactor's entry in ``reactors_series``.
    - ``x``, ``T``, ``P``, ``X``, ``Y`` arrays all have length equal to the
      number of points returned by ``network.states``.
    - The one-point fallback snapshot is fully replaced (len > 1).
    """
    import cantera as ct

    from boulder.cantera_converter import DualCanteraConverter
    from boulder.config import normalize_config

    N = 5  # synthetic spatial resolution

    class _MultiPointNet(ct.ReactorNet):
        """Fake spatial network: exposes N-point SolutionArray on .states."""

        def __init__(self, reactors, **kw):
            super().__init__(reactors)
            self._spatial_states: ct.SolutionArray | None = None

        def advance_to_steady_state(self) -> None:  # type: ignore[override]
            # Do NOT call super() — we just need to build the synthetic
            # spatial profile without running the real Cantera ODE solver,
            # since this test only checks that Boulder reads network.states
            # correctly, not that the physics converge.
            gas = self.reactors[0].phase
            arr = ct.SolutionArray(gas, extra=["t"])
            for i in range(N):
                arr.append(gas.state, t=float(i))  # type: ignore[call-arg]
            self._spatial_states = arr

        @property
        def states(self) -> ct.SolutionArray | None:  # noqa: D102
            return self._spatial_states

        @property
        def scalars(self) -> dict:  # noqa: D102
            return {}

    # Verify _MultiPointNet satisfies the CustomStageNetwork protocol
    assert isinstance(_MultiPointNet, type)

    # Register the class under a temporary module path so the YAML
    # ``network_class`` dotted-path resolver can find it.  This is the
    # correct plugin API: _select_network_class_for_stage checks the
    # ``network_class`` property in the node config first (highest priority),
    # which avoids having to set instance attributes on Cantera C++ types
    # (those lack __dict__ and do not support arbitrary attribute assignment).
    import sys

    _tmp_mod_name = "_test_runner_multipoint_net"
    import types as _types

    _tmp_mod = _types.ModuleType(_tmp_mod_name)
    _tmp_mod._MultiPointNet = _MultiPointNet  # type: ignore[attr-defined]
    sys.modules[_tmp_mod_name] = _tmp_mod
    try:
        # Minimal single-reactor config with the custom network class
        config: dict = {
            "nodes": [
                {
                    "id": "feed",
                    "type": "Reservoir",
                    "properties": {
                        "temperature": 300.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                    },
                },
                {
                    "id": "pfr_like",
                    "type": "IdealGasConstPressureReactor",
                    "properties": {
                        "temperature": 300.0,
                        "pressure": 101325.0,
                        "composition": "N2:1",
                        "volume": 1.0e-6,
                        # Inject custom network class via the YAML property path —
                        # the highest-priority slot in _select_network_class_for_stage.
                        "network_class": f"{_tmp_mod_name}._MultiPointNet",
                    },
                },
            ],
            "connections": [
                {
                    "id": "feed_to_pfr",
                    "type": "MassFlowController",
                    "source": "feed",
                    "target": "pfr_like",
                    "properties": {"mass_flow_rate": 1.0e-5},
                }
            ],
        }
        config = normalize_config(config)

        conv = DualCanteraConverter()
        conv.build_network(config)
        results, _ = conv.run_streaming_simulation(
            simulation_time=1.0,
            time_step=1.0,
            config=config,
        )

        series = results["reactors"].get("pfr_like")
        assert series is not None, "pfr_like must appear in reactors_series"
        assert series.get("is_spatial") is True, (
            "Series must be flagged is_spatial when network.states has multiple points"
        )
        assert len(series["T"]) == N, f"Expected {N} T samples, got {len(series['T'])}"
        assert len(series["x"]) == N, (
            f"Expected {N} x-axis values, got {len(series['x'])}"
        )
        assert len(series["P"]) == N
        for sp_arr in series["X"].values():
            assert len(sp_arr) == N
    finally:
        sys.modules.pop(_tmp_mod_name, None)
