"""Round-trip tests for the composite HDF5 payload store (all three tiers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cantera as ct
import numpy as np
import pytest

from boulder.payload_store import (
    gui_payload_from_solution_array,
    read_payload,
    write_payload,
)

MECH = "gri30.yaml"


def _real_state_series(n: int, with_t: bool) -> dict:
    """Build a physically-real, normalised series by actually setting the gas."""
    gas = ct.Solution(MECH)
    T = [1000.0 + 50 * i for i in range(n)]
    P = [101325.0] * n
    rows = []
    for i in range(n):
        gas.TPX = T[i], P[i], {"CH4": 1.0 + i, "O2": 2.0, "N2": 7.5}
        rows.append(gas.X.copy())
    Xmat = np.array(rows)
    names = gas.species_names
    series = {
        "T": T,
        "P": P,
        "X": {sp: [float(Xmat[i, j]) for i in range(n)] for j, sp in enumerate(names)},
    }
    if with_t:
        series["t"] = [1e-3 * i for i in range(n)]
    return series


def _payload(reactors: dict, **extra) -> dict:
    return {
        "status": "complete",
        "is_complete": True,
        "times": [0.0],
        "reactors_series": reactors,
        "reactor_reports": {},
        "connection_reports": {},
        "summary": [],
        "sankey_links": None,
        "sankey_nodes": None,
        **extra,
    }


def test_solution_tier_trajectory(tmp_path: Path):
    """A normalised state series WITH t → solution tier; Y derived; X exact."""
    s = _real_state_series(6, with_t=True)
    s["is_residence"] = True
    p = tmp_path / "result.h5"
    write_payload(p, _payload({"reactor": s}), MECH)
    out = read_payload(p)
    rt = out["reactors_series"]["reactor"]
    assert np.allclose(rt["T"], s["T"]) and np.allclose(rt["P"], s["P"])
    assert "t" in rt and np.allclose(rt["t"], s["t"])
    assert np.allclose(rt["X"]["CH4"], s["X"]["CH4"])
    assert abs(sum(v[0] for v in rt["Y"].values()) - 1.0) < 1e-9  # Y derived
    assert rt["is_residence"] is True


def test_solution_tier_steady_no_t(tmp_path: Path):
    """A normalised steady series (no t) still uses solution tier (had_t:false)."""
    s = _real_state_series(1, with_t=False)
    p = tmp_path / "result.h5"
    write_payload(p, _payload({"reactor": s}), MECH)
    out = read_payload(p)
    rt = out["reactors_series"]["reactor"]
    assert "t" not in rt  # original had no time axis → not fabricated
    assert np.allclose(rt["T"], s["T"])


def test_arrays_tier_off_mechanism(tmp_path: Path):
    """Species the mechanism can't represent → arrays tier, no Solution needed."""
    s = {
        "T": [1200.0, 1300.0],
        "P": [1e5, 1e5],
        "X": {"madeup_species": [0.4, 0.5], "other": [0.6, 0.5]},
        "t": [0.0, 1.0],
        "is_psr": True,
    }
    p = tmp_path / "result.h5"
    write_payload(p, _payload({"r": s}), MECH)
    # No mechanism passed on read → arrays tier must not need one.
    out = read_payload(p, mechanism_override="")
    rt = out["reactors_series"]["r"]
    assert np.allclose(rt["X"]["madeup_species"], [0.4, 0.5])
    assert rt["is_psr"] is True and np.allclose(rt["t"], [0.0, 1.0])


def test_arrays_tier_non_normalised_X(tmp_path: Path):
    """In-mechanism but X rows don't sum to 1 → arrays tier (no silent renorm, R2)."""
    s = {"T": [1200.0], "P": [1e5], "X": {"CH4": [0.4], "O2": [0.4]}, "t": [0.0]}
    p = tmp_path / "result.h5"
    write_payload(p, _payload({"r": s}), MECH)
    out = read_payload(p)
    rt = out["reactors_series"]["r"]
    # Preserved exactly (0.4/0.4), NOT renormalised to 0.5/0.5.
    assert np.allclose(rt["X"]["CH4"], [0.4]) and np.allclose(rt["X"]["O2"], [0.4])


def test_raw_tier_non_state(tmp_path: Path):
    """A non-state structure → raw tier, verbatim."""
    s = {"weird": [1, 2, 3], "note": "spatial-ish"}
    p = tmp_path / "result.h5"
    write_payload(p, _payload({"r": s}), MECH)
    out = read_payload(p)
    assert out["reactors_series"]["r"] == s


def test_spatial_series_stored_natively(tmp_path: Path):
    """A spatial reactor profile is stored as a native state sequence.

    x rides as a per-state extra column (native, NOT raw JSON), while the
    per-iteration fbs_convergence + flags ride in meta.
    """
    import h5py

    s = _real_state_series(4, with_t=False)
    s["x"] = [0.0, 0.1, 0.2, 0.3]  # axial position [m], per-state
    s["is_spatial"] = True
    s["fbs_convergence"] = [12.0, 3.0, 0.5]  # per-FBS-iteration, NOT per-state
    p = tmp_path / "result.h5"
    write_payload(p, _payload({"pfr": s}), MECH)

    with h5py.File(p, "r") as h:  # stored natively → a Cantera SolutionArray group
        assert "r0" in h
    out = read_payload(p)
    rt = out["reactors_series"]["pfr"]
    assert rt["x"] == s["x"]  # position axis preserved as extra col
    assert rt.get("is_spatial") is True  # flag preserved via meta
    assert rt["fbs_convergence"] == s["fbs_convergence"]  # off-shape array via meta


def test_derived_artifacts_preserved(tmp_path: Path):
    """Sankey / reports / summary survive the round-trip."""
    s = _real_state_series(3, with_t=True)
    payload = _payload(
        {"reactor": s},
        sankey_nodes=["a", "b"],
        sankey_links={"source": [0], "target": [1], "value": [1.0]},
        reactor_reports={"reactor": {"note": "x"}},
        code_str="# code",
    )
    p = tmp_path / "result.h5"
    write_payload(p, payload, MECH)
    out = read_payload(p)
    assert out["sankey_nodes"] == ["a", "b"]
    assert out["reactor_reports"] == {"reactor": {"note": "x"}}
    assert out["code_str"] == "# code"


def test_unresolved_mechanism_raises(tmp_path: Path):
    """A solution-tier entry with an unloadable mechanism raises (caller handles, R1)."""
    s = _real_state_series(3, with_t=True)
    p = tmp_path / "result.h5"
    write_payload(p, _payload({"reactor": s}), MECH)
    with pytest.raises(Exception):
        read_payload(p, mechanism_override="no_such_mechanism_xyz.yaml")


def test_multireactor_mechanism_switch(tmp_path: Path):
    """A multi-reactor, mechanism-switch network + reports/sankey.

    One stage on the cache mechanism (gri30) → solution tier; a downstream stage
    on a *different* species set (the mechanism can't represent it) → arrays tier,
    restorable with NO Solution. Both round-trip; derived artifacts preserved.
    """
    upstream = _real_state_series(4, with_t=True)  # gri30 → solution tier
    downstream: dict[str, Any] = {  # foreign species → arrays tier
        "T": [1800.0, 1700.0, 1600.0],
        "P": [1e5, 1e5, 1e5],
        "X": {
            "C2H2": [0.3, 0.35, 0.4],
            "H2": [0.5, 0.5, 0.5],
            "C(s)": [0.2, 0.15, 0.1],
        },
        "Y": {
            "C2H2": [0.3, 0.35, 0.4],
            "H2": [0.4, 0.4, 0.4],
            "C(s)": [0.3, 0.25, 0.2],
        },
        "t": [0.0, 0.5, 1.0],
    }
    payload = _payload(
        {"upstream": upstream, "downstream": downstream},
        reactor_reports={
            "upstream": {"T_out": 2000.0},
            "downstream": {"C_yield": 0.42},
        },
        sankey_nodes=["upstream", "downstream", "C(s)"],
        sankey_links={"source": [0, 1], "target": [1, 2], "value": [1.0, 0.4]},
    )
    p = tmp_path / "result.h5"
    write_payload(p, payload, MECH)
    out = read_payload(p)  # gri30 available; downstream (arrays) doesn't need it
    assert np.allclose(out["reactors_series"]["upstream"]["T"], upstream["T"])
    assert np.allclose(
        out["reactors_series"]["downstream"]["X"]["C2H2"], downstream["X"]["C2H2"]
    )
    assert np.allclose(
        out["reactors_series"]["downstream"]["Y"]["H2"], downstream["Y"]["H2"]
    )
    assert out["reactor_reports"]["downstream"]["C_yield"] == 0.42
    assert out["sankey_nodes"] == ["upstream", "downstream", "C(s)"]


def test_collection_composite_per_scenario(tmp_path: Path):
    """Many composites in one file, namespaced by scenario id.

    Appends don't wipe siblings; a multi-reactor scenario round-trips.
    """
    import h5py

    p = tmp_path / "scenarios.h5"
    s1 = _real_state_series(4, with_t=True)
    write_payload(p, _payload({"reactor": s1}), MECH, group="T0_1273K", fresh=False)
    # Second scenario, multi-reactor, appended — must not clobber the first.
    s2a = _real_state_series(3, with_t=True)
    s2b = _real_state_series(3, with_t=True)
    write_payload(
        p,
        _payload(
            {"upstream": s2a, "downstream": s2b}, reactor_reports={"upstream": {"q": 1}}
        ),
        MECH,
        group="T0_1573K",
        fresh=False,
    )

    with h5py.File(p, "r") as h:
        assert "T0_1273K" in h and "T0_1573K" in h  # both scenarios present

    g1 = read_payload(p, group="T0_1273K")
    assert np.allclose(g1["reactors_series"]["reactor"]["T"], s1["T"])
    g2 = read_payload(p, group="T0_1573K")
    assert set(g2["reactors_series"]) == {"upstream", "downstream"}
    assert g2["reactor_reports"] == {"upstream": {"q": 1}}


def test_shared_builder(tmp_path: Path):
    gas = ct.Solution(MECH)
    n = 4
    states = ct.SolutionArray(gas, shape=(n,), extra={"t": np.arange(n, dtype=float)})
    states.TP = [1000.0] * n, [1e5] * n
    gp = gui_payload_from_solution_array(states, "reactor")
    assert gp["is_complete"] and "reactor" in gp["reactors_series"]
    assert gp["reactors_series"]["reactor"]["is_residence"] is True
    assert len(gp["times"]) == n
