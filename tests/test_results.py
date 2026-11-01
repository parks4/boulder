"""Reading a result store from anywhere with :mod:`boulder.results`.

The store fixture is written for a config path that does not exist on this
machine, with a local copy of gri30 as its mechanism (so a SHA-256 is recorded),
which is what a store copied to another machine or share looks like.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict

import cantera as ct
import numpy as np
import pytest

pytest.importorskip("h5py")

from boulder import scenario_store  # noqa: E402
from boulder.cli import main as cli_main  # noqa: E402
from boulder.payload_store import gui_payload_from_solution_array  # noqa: E402
from boulder.results import MechanismMismatchError, open_results  # noqa: E402

GRI30 = Path(ct.__file__).parent / "data" / "gri30.yaml"
TEMPERATURES = (1200.0, 1400.0)


def _batch(mech: Path, T0: float) -> ct.SolutionArray:
    gas = ct.Solution(str(mech))
    gas.TPX = T0, ct.one_atm, "CH4:1, O2:2, N2:7.52"
    reactor = ct.IdealGasConstPressureReactor(gas)
    net = ct.ReactorNet([reactor])
    states = ct.SolutionArray(gas, extra=["t"])
    for t in np.linspace(0.0, 2e-3, 21):
        net.advance(t)
        states.append(reactor.phase.state, t=t)  # type: ignore[call-arg]
    return states


@pytest.fixture
def store(tmp_path: Path) -> Dict[str, object]:
    """Two scenarios (T0 = 1200 / 1400 K) of one reactor ``r0``, stamped for a foreign config."""
    mech = tmp_path / "mech" / "gri30.yaml"
    mech.parent.mkdir()
    shutil.copy(GRI30, mech)
    store_dir = tmp_path / "store"
    originals = {}
    for i, T0 in enumerate(TEMPERATURES):
        states = _batch(mech, T0)
        sid = f"case_{i}"
        scenario_store.write_entry(
            store_dir,
            sid,
            gui_payload=gui_payload_from_solution_array(states, "r0"),
            mechanism=str(mech),
            fingerprint=f"fp{i}",
            identity="/elsewhere/config.yaml",
            label=f"T0 = {T0:g} K",
            order=i,
            extra_attrs={"in.r0.temperature": T0, "peak_T": float(states.T.max())},
        )
        originals[sid] = states
    return {"dir": store_dir, "mech": mech, "originals": originals}


def test_opens_a_store_written_for_another_config(store):
    """A store stamped for another config opens and round-trips.

    A store stamped for another config lists every scenario, in run-set order,
    with its inputs and scalars; select() picks one by input value; states() returns
    the stored trajectory as a Cantera SolutionArray (same T and t, nothing re-solved).
    """
    rs = open_results(store["dir"])
    assert list(rs) == ["case_0", "case_1"]
    sc = rs.select(temperature=1400.0)
    assert sc.id == "case_1"
    assert sc.inputs == {"in.r0.temperature": 1400.0}
    assert sc.scalars["peak_T"] == pytest.approx(store["originals"]["case_1"].T.max())
    assert sc.reactors == ["r0"]
    arr = sc.states("r0")
    original = store["originals"]["case_1"]
    assert isinstance(arr, ct.SolutionArray)
    np.testing.assert_allclose(arr.T, original.T, rtol=1e-10)
    np.testing.assert_allclose(arr.t, original.t)
    cols = sc.series("r0", "t", "T", "X:CO2")
    np.testing.assert_allclose(cols["X:CO2"], original("CO2").X[:, 0], rtol=1e-10)


def test_mechanism_found_on_search_path_when_stored_path_is_gone(store):
    """A moved mechanism is found through search_path.

    When the stored mechanism path no longer exists, states() raises
    FileNotFoundError; the same file found through search_path is accepted.
    """
    moved = store["dir"].parent / "elsewhere"
    moved.mkdir()
    shutil.move(str(store["mech"]), moved / "gri30.yaml")
    with pytest.raises(FileNotFoundError):
        open_results(store["dir"])["case_0"].states("r0")
    arr = open_results(store["dir"], search_path=[moved])["case_0"].states("r0")
    assert arr.T[0] == pytest.approx(TEMPERATURES[0])


def test_mechanism_with_a_different_checksum_is_refused(store):
    """A mechanism with another SHA-256 is refused.

    A mechanism file whose SHA-256 differs from the stored one raises
    MechanismMismatchError; allow_mismatch=True turns it into a warning.
    """
    store["mech"].write_text(store["mech"].read_text() + "\n# edited\n")
    with pytest.raises(MechanismMismatchError):
        open_results(store["dir"])["case_0"].states("r0")
    with pytest.warns(UserWarning, match="SHA-256"):
        open_results(store["dir"], allow_mismatch=True)["case_0"].states("r0")


def test_cli_lists_and_exports(store, tmp_path, capsys):
    """The CLI lists scenarios and exports a trajectory.

    ``boulder results list`` prints one line per scenario with its inputs;
    ``boulder results export`` writes the reactor trajectory to a CSV file.
    """
    with pytest.raises(SystemExit) as exit_list:
        cli_main(["results", "list", str(store["dir"])])
    assert exit_list.value.code == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[0] for line in out] == ["case_0", "case_1"]
    assert "r0.temperature=1200.0" in out[0]

    csv = tmp_path / "r0.csv"
    with pytest.raises(SystemExit) as exit_export:
        cli_main(
            [
                "results",
                "export",
                str(store["dir"]),
                "case_0",
                "--reactor",
                "r0",
                "--csv",
                str(csv),
            ]
        )
    assert exit_export.value.code == 0
    lines = csv.read_text().splitlines()
    assert len(lines) == 1 + 21
