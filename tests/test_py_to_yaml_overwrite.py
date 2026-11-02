"""A conversion never overwrites an existing, possibly hand-edited, YAML."""

from __future__ import annotations

import textwrap
from pathlib import Path

from boulder.parser import convert_py_to_yaml

SCRIPT = """
import cantera as ct

gas = ct.Solution("h2o2.yaml")
gas.TPX = 300.0, ct.one_atm, "H2:1, N2:1"
inlet = ct.Reservoir(gas, name="inlet")
gas.TP = 900.0, ct.one_atm
r = ct.IdealGasReactor(gas, name="reactor")
r.volume = 1e-3
outlet = ct.Reservoir(gas, name="outlet")
mfc = ct.MassFlowController(inlet, r)
mfc.mass_flow_rate = 1e-4
valve = ct.Valve(r, outlet)
valve.valve_coeff = 1e-3
sim = ct.ReactorNet([r])
"""


def test_existing_yaml_survives_conversion_with_different_content(
    tmp_path: Path, capsys
) -> None:
    """A hand-edited ``<script>.yaml`` is left byte-for-byte unchanged.

    The conversion is written beside it under a ``_converted`` name, that new
    path is returned, and a warning names the untouched original.
    """
    script = tmp_path / "case.py"
    script.write_text(textwrap.dedent(SCRIPT), encoding="utf-8")
    existing = tmp_path / "case.yaml"
    hand_edited = "# hand edited\nmetadata:\n  name: my own edit\n"
    existing.write_text(hand_edited, encoding="utf-8")

    result = Path(convert_py_to_yaml(str(script)))

    assert existing.read_text(encoding="utf-8") == hand_edited
    assert result != existing
    assert result.name == "case_converted.yaml"
    assert result.exists()
    out = capsys.readouterr().out
    assert "different content" in out
    assert "Original file unchanged" in out
    assert not list(tmp_path.glob("*.tmp.yaml"))


def test_identical_existing_yaml_is_reused(tmp_path: Path) -> None:
    """Converting twice reuses the first YAML and leaves no temporary file."""
    script = tmp_path / "case.py"
    script.write_text(textwrap.dedent(SCRIPT), encoding="utf-8")

    first = Path(convert_py_to_yaml(str(script)))
    second = Path(convert_py_to_yaml(str(script)))

    assert first == second == tmp_path / "case.yaml"
    assert not list(tmp_path.glob("*.tmp.yaml"))
    assert not list(tmp_path.glob("*_converted*"))
