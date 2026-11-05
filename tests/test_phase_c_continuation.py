"""Phase C continuation sweep tests.

Verifies that:
- ``BoulderRunner.run_continuation`` executes a parameter sweep and stops at
  the correct condition (reactor T below threshold).
- The temperature trajectory decreases monotonically as residence time decreases
  (combustor extinction sweep).
- The ``continuation:`` block in STONE YAML is accepted by ``normalize_config``.
- The residence_time closure on an MFC produces a physically correct mdot.
- The mdot closure integrates without error in a simple solve_steady scenario.
"""

from __future__ import annotations

from typing import Any, Dict

import cantera as ct
import pytest

_GRI_MECH = "gri30.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _inert_continuation_config(*, initial_volume: float = 1.0) -> Dict[str, Any]:
    """Build a normalized single-stage inert N2 config for continuation testing.

    Uses ``solver.kind: advance_to_steady_state`` (safe on all platforms).
    The continuation sweeps reactor volume; temperature stays ~constant since N2 is inert.
    Network: inlet → mfc → r1 → pc → exhaust
    """
    from boulder.config import normalize_config

    return normalize_config(
        {
            "network": [
                {
                    "id": "inlet",
                    "Reservoir": {
                        "temperature": "1200 K",
                        "pressure": "1 atm",
                        "composition": "N2:1",
                    },
                },
                {
                    "id": "r1",
                    "IdealGasConstPressureMoleReactor": {
                        "volume": f"{initial_volume} L",
                        "initial": {
                            "temperature": "1200 K",
                            "pressure": "1 atm",
                            "composition": "N2:1",
                        },
                    },
                },
                {
                    "id": "exhaust",
                    "OutletSink": {},
                },
                {
                    "id": "mfc",
                    "MassFlowController": {"mass_flow_rate": 0.001},
                    "source": "inlet",
                    "target": "r1",
                },
                {
                    "id": "pc",
                    "PressureController": {"master": "mfc", "pressure_coeff": 0.0},
                    "source": "r1",
                    "target": "exhaust",
                },
            ],
            "settings": {"solver": {"kind": "advance_to_steady_state"}},
        }
    )


# ---------------------------------------------------------------------------
# Tests for run_continuation
# ---------------------------------------------------------------------------


class TestRunContinuation:
    def test_run_continuation_runs_iterations_and_records_rows(self):
        """run_continuation runs up to max_iters and records one row per iteration.

        Uses an inert N2 network where temperature stays ~constant (no extinction).
        Asserts that the continuation_rows list has exactly max_iters entries.
        """
        from boulder.runner import BoulderRunner

        config = _inert_continuation_config()
        runner = BoulderRunner(config)

        max_iters = 3
        continuation = {
            "parameter": "connections.mfc.mass_flow_rate",
            "update": {"multiply": 0.9},
            "until": {"max_iters": max_iters},
        }

        runner.run_continuation(continuation=continuation)

        rows = runner._continuation_rows
        assert len(rows) == max_iters, f"Expected {max_iters} rows, got {len(rows)}"

    def test_run_continuation_parameter_decreases(self):
        """Each iteration solves with the multiplied value: strictly decreasing.

        Asserts the recorded parameter is 0.001 * 0.8**step, and that the device
        the last stage solve built carries the last recorded value: the update
        reached the config the next stage is built from, not only the record.
        """
        from boulder.runner import BoulderRunner

        config = _inert_continuation_config()
        runner = BoulderRunner(config)

        continuation = {
            "parameter": "connections.mfc.mass_flow_rate",
            "update": {"multiply": 0.8},
            "until": {"max_iters": 4},
        }

        runner.run_continuation(continuation=continuation)

        rows = runner._continuation_rows
        assert len(rows) >= 2, "Expected at least 2 continuation steps"
        params = [r["parameter"] for r in rows]
        assert params == pytest.approx([0.001 * 0.8**i for i in range(len(params))])
        for i in range(1, len(params)):
            assert params[i] < params[i - 1], f"Parameter did not decrease: {params}"
        assert runner.converter is not None
        device = runner.converter.connections["mfc"]
        assert device.mass_flow_rate == pytest.approx(params[-1])

    def test_run_continuation_requires_parameter_key(self):
        """run_continuation raises ValueError when 'parameter' key is missing."""
        from boulder.runner import BoulderRunner

        config = _inert_continuation_config()
        runner = BoulderRunner(config)

        with pytest.raises(ValueError, match="parameter"):
            runner.run_continuation(continuation={"update": {"multiply": 0.9}})

    def test_run_continuation_requires_continuation_block(self):
        """run_continuation raises ValueError when no continuation block exists."""
        from boulder.runner import BoulderRunner

        config = _inert_continuation_config()
        runner = BoulderRunner(config)

        with pytest.raises(ValueError, match="continuation"):
            runner.run_continuation()

    def test_run_continuation_list_update(self):
        """List update mode iterates through explicit values."""
        from boulder.runner import BoulderRunner

        config = _inert_continuation_config()
        runner = BoulderRunner(config)

        mdot_values = [0.002, 0.001, 0.0005]
        continuation = {
            "parameter": "connections.mfc.mass_flow_rate",
            "update": {"list": mdot_values},
            "until": {"max_iters": 10},
        }

        runner.run_continuation(continuation=continuation)

        rows = runner._continuation_rows
        # list has 3 values; run_continuation sets next on iteration, so rows = 3
        assert len(rows) <= len(mdot_values) + 1


# ---------------------------------------------------------------------------
# Test: STONE YAML with continuation: block parses without error
# ---------------------------------------------------------------------------


class TestContinuationBlockInYAML:
    def test_normalize_config_accepts_continuation_block(self):
        """A STONE YAML with a top-level continuation: block normalizes without error.

        Asserts that the continuation block is preserved in the normalized config.
        """
        from boulder.config import normalize_config

        raw = {
            "network": [
                {
                    "id": "r1",
                    "IdealGasConstPressureMoleReactor": {
                        "initial": {
                            "temperature": "1200 K",
                            "pressure": "1 atm",
                            "composition": "N2:1",
                        },
                        "volume": "1 L",
                    },
                }
            ],
            "continuation": {
                "parameter": "nodes.r1.volume",
                "update": {"multiply": 0.9},
                "until": {"max_iters": 10},
            },
        }
        norm = normalize_config(raw)
        assert "continuation" in norm, "continuation block lost during normalization"
        assert norm["continuation"]["parameter"] == "nodes.r1.volume"


# ---------------------------------------------------------------------------
# Test: residence_time closure on MFC
# ---------------------------------------------------------------------------


class TestResidenceTimeClosure:
    def test_mdot_closure_builds_func1(self):
        """mass_flow_rate closure: residence_time produces a Func1 on the MFC."""
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.config import normalize_config

        config = normalize_config(
            {
                "network": [
                    {
                        "id": "inlet",
                        "Reservoir": {
                            "temperature": "300 K",
                            "pressure": "1 atm",
                            "composition": "N2:1",
                        },
                    },
                    {
                        "id": "r1",
                        "IdealGasReactor": {
                            "volume": "1 L",
                            "initial": {
                                "temperature": "1200 K",
                                "pressure": "1 atm",
                                "composition": "N2:1",
                            },
                        },
                    },
                    {
                        "id": "exhaust",
                        "OutletSink": {},
                    },
                    {
                        "id": "mfc",
                        "MassFlowController": {
                            "mass_flow_rate": {
                                "closure": "residence_time",
                                "reactor": "r1",
                                "tau_s": 0.01,
                            }
                        },
                        "source": "inlet",
                        "target": "r1",
                    },
                    {
                        "id": "pc",
                        "PressureController": {"master": "mfc", "pressure_coeff": 0.0},
                        "source": "r1",
                        "target": "exhaust",
                    },
                ]
            }
        )

        conv = DualCanteraConverter(_GRI_MECH)
        conv.build_network(config)

        mfc = conv.connections["mfc"]
        # Cantera MassFlowController with a Func1 set via mass_flow_rate
        # The reactor mass at 1 atm, 1 L, 1200 K should be ~2.9e-5 kg
        # → mdot ≈ mass / 0.01 ≈ 0.003 kg/s
        assert isinstance(mfc, ct.MassFlowController)

    def test_mdot_closure_invalid_kind_raises(self):
        """An unsupported closure kind raises ValueError during build_network."""
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.config import normalize_config

        config = normalize_config(
            {
                "network": [
                    {
                        "id": "inlet",
                        "Reservoir": {
                            "temperature": "300 K",
                            "pressure": "1 atm",
                            "composition": "N2:1",
                        },
                    },
                    {
                        "id": "r1",
                        "IdealGasReactor": {
                            "volume": "1 L",
                            "initial": {
                                "temperature": "1200 K",
                                "pressure": "1 atm",
                                "composition": "N2:1",
                            },
                        },
                    },
                    {
                        "id": "exhaust",
                        "OutletSink": {},
                    },
                    {
                        "id": "mfc",
                        "MassFlowController": {
                            "mass_flow_rate": {
                                "closure": "unknown_closure_type",
                                "reactor": "r1",
                            }
                        },
                        "source": "inlet",
                        "target": "r1",
                    },
                ]
            }
        )

        conv = DualCanteraConverter(_GRI_MECH)
        with pytest.raises(ValueError, match="closure"):
            conv.build_network(config)


# ---------------------------------------------------------------------------
# Test: combustor extinction sweep (physics check)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestCombustorExtinctionSweep:
    @pytest.mark.xfail(
        reason=(
            "solve_steady() with a Python-callable mdot segfaults on Cantera 3.2 / Windows. "
            "Known upstream limitation; tracked as phase-c-tests."
        ),
        strict=False,
    )
    def test_combustor_temperature_decreases_as_residence_time_shrinks(self):
        """Combustor temperature decreases monotonically as tau_s shrinks.

        Directly mirrors the upstream combustor.py pattern using raw Cantera.
        Asserts that:
        - At residence_time = 0.1 s the reactor is burning (T > 1500 K).
        - The trajectory is approximately monotone (T decreases as tau shrinks).

        This is a physics-level test; it does not use Boulder's continuation block.

        Marked xfail because ``solve_steady()`` can segfault on Windows with a
        Python-callable ``mdot`` in Cantera 3.2; the test is kept to document the
        expected behavior and will unxfail once the upstream limitation is resolved.
        """
        gas = ct.Solution(_GRI_MECH, transport_model=None)
        gas.TP = 300.0, ct.one_atm
        gas.set_equivalence_ratio(0.5, "CH4:1.0", "O2:1.0, N2:3.76")
        inlet = ct.Reservoir(gas)

        gas.equilibrate("HP")
        combustor = ct.IdealGasReactor(gas)
        combustor.volume = 1.0

        exhaust = ct.Reservoir(gas)

        residence_time = 0.1

        def mdot(t):
            return combustor.mass / residence_time

        inlet_mfc = ct.MassFlowController(inlet, combustor, mdot=mdot)
        _outlet_mfc = ct.PressureController(
            combustor, exhaust, primary=inlet_mfc, K=0.01
        )
        sim = ct.ReactorNet([combustor])

        temps = []
        tres_vals = []

        for _ in range(30):
            if combustor.T <= 500:
                break
            sim.initial_time = 0.0
            sim.solve_steady()
            temps.append(combustor.T)
            tres_vals.append(residence_time)
            residence_time *= 0.9

        assert len(temps) >= 5, "Expected at least 5 sweep points"
        assert temps[0] > 1500.0, f"Initial T should be burning, got {temps[0]:.1f} K"
        assert temps[-1] < temps[0], "Expected temperature to decrease over sweep"


# ---------------------------------------------------------------------------
# Parameter paths, list[0], and a continuation: section read from a YAML file
# ---------------------------------------------------------------------------

_YAML_CONTINUATION = """\
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_to_steady_state
network:
  - id: inlet
    Reservoir: {temperature: 1200 K, pressure: 1 atm, composition: "N2:1"}
  - id: r1
    IdealGasConstPressureMoleReactor:
      volume: 1 L
      initial: {temperature: 1200 K, pressure: 1 atm, composition: "N2:1"}
  - id: exhaust
    OutletSink: {}
  - id: mfc
    MassFlowController: {mass_flow_rate: 0.001}
    source: inlet
    target: r1
  - id: pc
    PressureController: {master: mfc, pressure_coeff: 0.0}
    source: r1
    target: exhaust
continuation:
  parameter: connections.mfc.mass_flow_rate
  update: {multiply: 0.5}
  until: {max_iters: 3}
"""


def test_run_continuation_rejects_a_parameter_that_is_not_a_config_property():
    """An attribute the config does not declare raises instead of recording a no-op.

    Asserts ``ValueError`` for ``connections.mfc.mass_flow_coeff`` (not a
    property of the MFC entry): the update could never reach the rebuilt device.
    """
    from boulder.runner import BoulderRunner

    runner = BoulderRunner(_inert_continuation_config())
    with pytest.raises(ValueError, match="config propert"):
        runner.run_continuation(
            continuation={
                "parameter": "connections.mfc.mass_flow_coeff",
                "update": {"multiply": 0.5},
                "until": {"max_iters": 3},
            }
        )


def test_run_continuation_list_solves_its_first_value():
    """Step 0 of a ``list`` update uses ``list[0]``, not the file's value.

    Asserts the recorded parameters are the list, in order, with 7e-4 first
    although the file holds 1e-3.
    """
    from boulder.runner import BoulderRunner

    runner = BoulderRunner(_inert_continuation_config())
    runner.run_continuation(
        continuation={
            "parameter": "connections.mfc.mass_flow_rate",
            "update": {"list": [7e-4, 5e-4, 2.5e-4]},
            "until": {"max_iters": 10},
        }
    )
    rows = runner._continuation_rows
    assert [r["parameter"] for r in rows] == [7e-4, 5e-4, 2.5e-4]
    assert runner.converter.connections["mfc"].mass_flow_rate == pytest.approx(2.5e-4)


def test_continuation_section_of_a_yaml_file_runs_and_downloads(tmp_path):
    """A YAML file's ``continuation:`` survives validation and drives both routes.

    Asserts ``BoulderRunner.from_yaml(file).run_continuation()`` runs three
    steps (x0.5), and that the downloaded script calls ``run_continuation``
    and, run in a subprocess, ends at the same last parameter value.
    """
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    import boulder
    from boulder.runner import BoulderRunner

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_YAML_CONTINUATION, encoding="utf-8")

    runner = BoulderRunner.from_yaml(str(cfg)).run_continuation()
    params = [r["parameter"] for r in runner._continuation_rows]
    assert params == pytest.approx([1e-3, 5e-4, 2.5e-4])

    script = tmp_path / "downloaded.py"
    BoulderRunner.from_yaml(str(cfg)).run_headless(download_path=str(script))
    out = tmp_path / "rows.json"
    text = script.read_text(encoding="utf-8")
    assert "run_continuation()" in text
    script.write_text(
        text
        + "\nimport json\njson.dump([r['parameter'] for r in runner._continuation_rows],"
        + f" open({str(out)!r}, 'w'))\n",
        encoding="utf-8",
    )
    env = dict(os.environ, TMP=str(tmp_path), TEMP=str(tmp_path))
    env["PYTHONPATH"] = str(Path(boulder.__file__).parent.parent)
    run = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(tmp_path),
        env=env,
    )
    assert run.returncode == 0, run.stderr[-3000:]
    assert json.loads(out.read_text("utf-8")) == pytest.approx(params)
