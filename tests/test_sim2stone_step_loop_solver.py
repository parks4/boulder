from __future__ import annotations

from pathlib import Path

import cantera as ct  # type: ignore
import pytest

from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.sim2stone import sim_to_stone_yaml


def test_step_loop_source_emits_advance_grid_matching_original_end_time(
    tmp_path: Path,
) -> None:
    """A ``while t < t_end: t = net.step()`` source emits advance_grid.

    Regression: sim2stone previously only recognized ``net.advance(...)``
    inside a transient while-loop; a script using the equally common
    ``net.step()`` idiom (e.g. upstream's continuous_reactor.py) got no
    solver hint at all and silently defaulted to ``advance_to_steady_state``
    — a different integration algorithm than the source actually used. The
    emitted grid's ``stop`` must match the source's own end-time threshold,
    whatever that threshold variable is named.
    """
    script = tmp_path / "step_loop_source.py"
    script.write_text(
        "max_simulation_time = 50.0\n"
        "t = 0.0\n"
        "while t < max_simulation_time:\n"
        "    t = reactor_network.step()\n",
        encoding="utf-8",
    )

    gas = ct.Solution("gri30.yaml")
    gas.TPX = 300.0, ct.one_atm, "CH4:1"
    r = ct.IdealGasReactor(gas, name="R1")
    sim = ct.ReactorNet([r])

    yaml_str = sim_to_stone_yaml(
        sim, default_mechanism="gri30.yaml", source_file=str(script)
    )
    normalized = normalize_config(load_yaml_string_with_comments(yaml_str))

    solver = normalized["settings"]["solver"]
    assert solver["kind"] == "advance_grid"
    assert solver["grid"]["stop"] == pytest.approx(50.0)
