"""Two ways to declare a run-set that a single-target axis could not express.

Both exist because real sweeps hit limits of the original `sweep:` block:

* **Multi-target axis** — one swept value must reach several config paths at
  once, because they are the same physical quantity on different nodes (an
  inlet reservoir's temperature and the isothermal reactor it feeds). Sweeping
  only one is physically inconsistent; crossing them produces nonsense pairs.
* **`sweep.runner`** — the points can only be produced by running them: solved
  sequentially with each warm-started from the last, or continuing until a
  condition (extinction) that fixes the length only at runtime.

The second replaces Boulder *guessing*: it used to execute any file named
`run_sweep.py` next to the config. That is deliberately still ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from boulder.runset import (  # noqa: E402
    expand_scenarios,
    sweep_runner_of,
    sweeps_of,
)

_BASE: Dict[str, Any] = {
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "network": [
        {"id": "tank", "Reservoir": {"temperature": 925.0, "composition": "CH4:1"}},
        {
            "id": "reactor",
            "IdealGasMoleReactor": {
                "energy": "off",
                "initial": {"temperature": 925.0, "composition": "CH4:1"},
            },
        },
    ],
}


def _cfg(**extra: Any) -> Dict[str, Any]:
    import copy

    cfg = copy.deepcopy(_BASE)
    cfg.update(extra)
    return cfg


# --------------------------------------------------------------------------- #
# Multi-target axis
# --------------------------------------------------------------------------- #


def test_one_value_reaches_every_declared_path() -> None:
    """The point of the feature: both nodes move together, in lockstep."""
    runs = expand_scenarios(
        _cfg(
            sweep={
                "inlet_temperature": {
                    "path": [
                        "network[id=tank].Reservoir.temperature",
                        "network[id=reactor].IdealGasMoleReactor.initial.temperature",
                    ],
                    "values": [650, 1100],
                }
            }
        )
    )

    assert len(runs) == 2, "two values -> two points, not a cross product"
    by_value = {}
    for _sid, cfg in runs:
        node = {n["id"]: n for n in cfg["network"]}
        tank_t = node["tank"]["Reservoir"]["temperature"]
        reactor_t = node["reactor"]["IdealGasMoleReactor"]["initial"]["temperature"]
        assert tank_t == reactor_t, "paths drifted -- they must move as one"
        by_value[tank_t] = reactor_t
    assert sorted(by_value) == [650, 1100]


def test_a_single_string_path_still_works() -> None:
    """Backward compatibility: the overwhelmingly common form is unchanged."""
    runs = expand_scenarios(
        _cfg(
            sweep={
                "t": {"path": "network[id=tank].Reservoir.temperature", "values": [700]}
            }
        )
    )
    assert len(runs) == 1
    node = {n["id"]: n for n in runs[0][1]["network"]}
    assert node["tank"]["Reservoir"]["temperature"] == 700
    # The untargeted node keeps the base value.
    assert node["reactor"]["IdealGasMoleReactor"]["initial"]["temperature"] == 925.0


def test_scenario_ids_do_not_grow_with_path_count() -> None:
    """A 2-path axis must not produce a doubled, unreadable id."""
    single = expand_scenarios(
        _cfg(
            sweep={
                "t": {"path": "network[id=tank].Reservoir.temperature", "values": [650]}
            }
        )
    )
    multi = expand_scenarios(
        _cfg(
            sweep={
                "t": {
                    "path": [
                        "network[id=tank].Reservoir.temperature",
                        "network[id=reactor].IdealGasMoleReactor.initial.temperature",
                    ],
                    "values": [650],
                }
            }
        )
    )
    assert single[0][0] == multi[0][0]


def test_a_malformed_path_list_fails_loudly() -> None:
    with pytest.raises(ValueError, match="dotted string or a list"):
        expand_scenarios(_cfg(sweep={"t": {"path": [None], "values": [1]}}))


# --------------------------------------------------------------------------- #
# sweep.runner
# --------------------------------------------------------------------------- #


def test_runner_is_read_but_never_treated_as_an_axis() -> None:
    """`runner` configures the run-set; iterating it as an axis would crash."""
    cfg = _cfg(sweep={"runner": "pkg.mod:run"})
    assert sweep_runner_of(cfg) == "pkg.mod:run"
    assert sweeps_of(cfg) == {}, "reserved key leaked into the axis map"


def test_runner_coexists_with_real_axes() -> None:
    cfg = _cfg(
        sweep={
            "runner": "pkg.mod:run",
            "t": {"path": "network[id=tank].Reservoir.temperature", "values": [1, 2]},
        }
    )
    assert sweep_runner_of(cfg) == "pkg.mod:run"
    assert list(sweeps_of(cfg)) == ["t"]
    # A sweep-only config gets no BASELINE entry (that is the `scenarios:`
    # case); the two axis points are the whole run-set.
    assert len(expand_scenarios(cfg)) == 2


def test_no_runner_declared_reads_as_none() -> None:
    assert sweep_runner_of(_cfg()) is None
    assert sweep_runner_of(_cfg(sweep={"t": {"path": "a.b", "values": [1]}})) is None


def test_a_config_with_only_a_runner_still_counts_as_a_run_set(tmp_path: Path) -> None:
    """Without this the Run Sweep button and Scenario pane stay hidden.

    Exactly how boulder_examples' scripted sweeps disappeared: their configs
    declare no axes at all, so a run-set check based purely on axes reported
    "nothing to run".
    """
    from boulder.api.routes.sweep import has_run_set

    cfg = _cfg(sweep={"runner": "pkg.mod:run"})
    assert has_run_set(cfg, str(tmp_path / "config.yaml")) is True


def test_a_bare_run_sweep_py_is_still_not_a_run_set(tmp_path: Path) -> None:
    """Filename discovery stays gone -- the runner must be declared."""
    from boulder.api.routes.sweep import has_run_set

    cfg = tmp_path / "config.yaml"
    cfg.write_text("metadata: {}\n", encoding="utf-8")
    (tmp_path / "run_sweep.py").write_text("", encoding="utf-8")
    assert has_run_set({}, str(cfg)) is False


def test_host_runner_is_called_once_even_if_it_raises_a_type_error() -> None:
    """Arity must be decided by signature, not by catching TypeError.

    A TypeError raised *inside* a runner would otherwise be mistaken for
    "wrong arity" and re-invoke it, writing the collection store twice.
    """
    from boulder.api.routes import sweep as sweep_route

    calls: List[Any] = []

    def _runner(store: Path) -> None:  # no `progress` parameter
        calls.append(store)
        raise TypeError("failure from inside the runner")

    from unittest.mock import patch

    import boulder.cantera_converter as cc

    with patch.object(cc, "resolve_dotted_path", return_value=_runner):
        with pytest.raises(TypeError, match="from inside the runner"):
            sweep_route._run_host_sweep("pkg.mod:run", {}, Path("store.h5"))

    assert len(calls) == 1, "runner was invoked more than once"


def test_a_host_runner_sweep_reaches_a_terminal_status(tmp_path: Path) -> None:
    """The job must end 'done', not sit at 'running' forever.

    The host owns the store, so this path skips Boulder's own finalisation --
    easy to skip the terminal bookkeeping with it and leave the Scenario pane
    polling a finished sweep indefinitely.
    """
    import time
    from unittest.mock import patch

    import h5py
    import pytest as _pytest

    _pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from boulder.api.main import create_app
    from boulder.runner import BoulderRunner

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "phases:\n  gas:\n    mechanism: gri30.yaml\n"
        "network:\n- id: feed\n  Reservoir:\n    temperature: 300\n"
        "    composition: 'CH4:1'\n"
        'sweep:\n  runner: "pkg.mod:run"\n',
        encoding="utf-8",
    )

    def _runner(store_path: Path, progress: Any = None) -> None:
        with h5py.File(str(store_path), "w") as handle:
            handle.create_group("a").create_dataset("payload_json", data=b"{}")

    app = create_app()
    client = TestClient(app)
    client.__enter__()
    app.state.preloaded_config_path = str(cfg)
    app.state.preloaded_raw = BoulderRunner.load(str(cfg))
    try:
        import boulder.cantera_converter as cc

        with patch.object(cc, "resolve_dotted_path", return_value=_runner):
            resp = client.post("/api/sweep/run", json={})
            assert resp.status_code == 200, resp.text
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if app.state.sweep_job.get("status") in ("done", "error"):
                    break
                time.sleep(0.02)

        assert app.state.sweep_job.get("status") == "done", app.state.sweep_job
    finally:
        client.__exit__(None, None, None)


def test_host_runner_receives_progress_when_it_asks_for_it() -> None:
    from boulder.api.routes import sweep as sweep_route

    state: Dict[str, Any] = {}

    def _runner(store: Path, progress: Any = None) -> None:
        progress(2, 5, "scenario 2/5")

    from unittest.mock import patch

    import boulder.cantera_converter as cc

    with patch.object(cc, "resolve_dotted_path", return_value=_runner):
        sweep_route._run_host_sweep("pkg.mod:run", state, Path("store.h5"))

    assert state["current"] == 2
    assert state["total"] == 5
    assert state["last_line"] == "scenario 2/5"
