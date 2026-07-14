"""Regression test: sim2stone's emitted connection order must not depend on
Python object ``id()`` (a memory address), which varies between process runs.

Bug: the wall-export loop sorted walls by
``key=lambda w: (id(w.left_reactor), id(w.right_reactor))``, and the
flow-device export loop broke ties with ``id(d)``. Since ``id()`` values are
different every time the interpreter starts (heap/ASLR), regenerating the
*same* example script in two separate ``python`` invocations could silently
reorder Walls/MassFlowControllers/Valves in the emitted YAML even though
their contents were identical -- producing spurious diffs on regeneration
(observed repeatedly in boulder_examples for reactor2.yaml and mix1.yaml).

This test runs the same conversion twice, each in its own subprocess (so the
two runs get independent, unrelated ``id()`` assignments), and asserts the
ordered list of ids in the emitted ``network:`` block is byte-for-byte
identical.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap

_BUILD_AND_CONVERT_SCRIPT = textwrap.dedent(
    """
    import sys

    import cantera as ct

    from boulder.sim2stone import sim_to_stone_yaml

    gas = ct.Solution("h2o2.yaml")
    gas.TPX = 900.0, ct.one_atm, "H2:1, O2:1, N2:2"

    inlet = ct.Reservoir(gas, name="inlet")
    outlet = ct.Reservoir(gas, name="outlet")

    r_a = ct.IdealGasReactor(gas, name="reactor_alpha")
    r_b = ct.IdealGasReactor(gas, name="reactor_beta")
    r_c = ct.IdealGasReactor(gas, name="reactor_gamma")

    ct.MassFlowController(inlet, r_a, mdot=0.01, name="mfc_in_alpha")
    ct.MassFlowController(r_a, r_b, mdot=0.01, name="mfc_alpha_beta")
    ct.MassFlowController(r_b, r_c, mdot=0.01, name="mfc_beta_gamma")
    ct.Valve(r_c, outlet, K=0.01, name="valve_out")

    ct.Wall(r_a, r_b, name="wall_alpha_beta", U=5.0, A=1.0)
    ct.Wall(r_b, r_c, name="wall_beta_gamma", U=5.0, A=1.0)
    ct.Wall(r_a, r_c, name="wall_alpha_gamma", U=5.0, A=1.0)

    sim = ct.ReactorNet([r_a, r_b, r_c])
    yaml_str = sim_to_stone_yaml(
        sim, default_mechanism="h2o2.yaml", include_comments=False
    )
    sys.stdout.write(yaml_str)
    """
)

_ID_RE = re.compile(r"^\s*-?\s*id:\s*(\S+)", re.MULTILINE)


def _run_conversion_in_subprocess() -> str:
    result = subprocess.run(
        [sys.executable, "-c", _BUILD_AND_CONVERT_SCRIPT],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_connection_order_is_stable_across_process_runs() -> None:
    """Regenerating the same network in two fresh processes must not reorder."""
    yaml_run_1 = _run_conversion_in_subprocess()
    yaml_run_2 = _run_conversion_in_subprocess()

    ids_run_1 = _ID_RE.findall(yaml_run_1)
    ids_run_2 = _ID_RE.findall(yaml_run_2)

    # Sanity check: the network actually has the objects we expect (nodes +
    # 4 flow devices + 3 walls), so the ordering assertion below is meaningful.
    assert len(ids_run_1) == 12, f"unexpected id count: {ids_run_1!r}"

    assert ids_run_1 == ids_run_2, (
        "Connection order changed between two separate process runs of the "
        "identical conversion -- likely an id()-based (memory address) sort "
        f"creeping back in.\nrun 1: {ids_run_1}\nrun 2: {ids_run_2}"
    )
