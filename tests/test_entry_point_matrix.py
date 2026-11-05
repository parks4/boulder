"""One config through every run path: the four entry points must agree.

The same run is assembled four ways: headless ``--run``, GUI Run
(``POST /api/simulations``), GUI Sweep (``POST /api/sweep/run``) and CLI
``--sweep --headless``.  A neutral gri30 network with one override scenario is
solved through each, with a host converter subclass (its own
``resolve_mechanism``) and recording hooks registered through a plugin.  For
each pair of paths the stored fingerprint, the stored entry attributes, the
stored run definition, the hook / contributor calls and the time grid are
compared; the whole matrix runs for a single file and for a ``from:`` leaf.
A fifth path, the script users receive (written by the real download entry,
``--headless --download``), is run in a subprocess and its reactor,
stream-point and trajectory states are compared with the pipeline's, for those
two files and for a two-mechanism case with a by-name switch plugin and a
host reactor subclass; the script's class listing is checked too.
The stored definition, run alone as its own file, must hash to the same entry,
and no path may write the user's files.

Notes on the paths: all four run in-process and end in the one run-set
pipeline.  A headless single run solves the base entry (``BASELINE``) only; the
override scenario (``hot``) is reachable through GUI Run (``scenario_id``) and
both sweeps.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

pytest.importorskip("h5py")
pytest.importorskip("fastapi")

import cantera as ct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from boulder import cantera_converter, cli, result_cache, scenario_store  # noqa: E402
from boulder.api import main as api_main  # noqa: E402
from boulder.runner import BoulderRunner  # noqa: E402
from boulder.runset import resolve_store_dir  # noqa: E402

pytestmark = pytest.mark.slow

_CONFIG = """\
phases:
  gas:
    mechanism: gri30.yaml
settings:
  end_time: 0.01
  dt: 0.005
  solver:
    kind: advance_grid
    grid:
      start: 0.0
      stop: 0.01
      dt: 0.005
network:
  - id: feed
    Reservoir:
      temperature: 300
      pressure: 101325
      composition: "N2:1"
  - id: reactor
    IdealGasReactor:
      volume: 1.0
      initial:
        temperature: 300
        pressure: 101325
        composition: "N2:1"
  - id: outlet
    Reservoir:
      temperature: 300
      pressure: 101325
      composition: "N2:1"
  - id: inlet
    MassFlowController:
      mass_flow_rate: 0.01
    source: feed
    target: reactor
  - id: valve
    Valve:
      valve_coeff: 1.0
    source: reactor
    target: outlet
scenarios:
  hot:
    network:
      - id: feed
        Reservoir:
          temperature: 350
"""

#: A host plugin: converter subclass resolving mechanisms under a directory,
#: plus recording hooks.  Calls go to a JSON-lines file named by an env var so
#: the CLI sweep subprocess records the same way as the in-process paths.
_PLUGIN = """\
import json
import os
from pathlib import Path

import cantera as ct

from boulder import register_reactor_builder
from boulder.cantera_converter import DualCanteraConverter
from boulder.result_cache import CacheContributorPlugin, register_cache_contributor
from boulder.runner import BoulderRunner


class HostRunner(BoulderRunner):
    # A host's runner subclass: the downloaded script must import and use it.
    pass


class ExampleReactor(ct.IdealGasConstPressureMoleReactor):
    # A host's reactor subclass: the downloaded script must list it by name.
    pass


def _build_example_reactor(converter, node):
    props = node.get("properties", {})
    initial = props["initial"]
    gas = converter.create_solution("gri30.yaml")
    gas.TPX = (
        float(initial["temperature"]),
        float(initial["pressure"]),
        str(initial["composition"]),
    )
    reactor = ExampleReactor(gas)
    reactor.volume = float(props["volume"])
    return reactor


def _record(kind, **fields):
    with open(os.environ["EPM_RECORD"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": kind, **fields}) + "\\n")


class HostConverter(DualCanteraConverter):
    def resolve_mechanism(self, name):
        return str(Path(os.environ["EPM_MECH_DIR"]) / Path(name).name)


class Recorder(CacheContributorPlugin):
    contributor_id = "epm_recorder"

    def contribute(self, config, converter, simulation_result, fingerprint, adir):
        _record("contributor", fingerprint=fingerprint)


def _attrs(sid, cfg, gui):
    _record("scenario_attrs", sid=sid)
    return {"epm_kpi": 1.0}


def _solved(sid, config, conv, result, fingerprint, gui, mechanism):
    _record("on_scenario_solved", sid=sid)


def _by_name_switch(gas, target, htol, Xtol):
    import cantera as ct

    out = ct.Solution(target)
    known = {s: x for s, x in zip(gas.species_names, gas.X) if s in out.species_names}
    out.TPX = gas.T, gas.P, known
    return out


def register_plugins(plugins):
    plugins.converter_class = HostConverter
    plugins.mechanism_switch_fn = _by_name_switch
    register_reactor_builder(
        plugins,
        kind="ExampleReactor",
        builder=_build_example_reactor,
        reactor_class=ExampleReactor,
    )
    plugins.scenario_attrs = _attrs
    plugins.on_scenario_solved = _solved
    register_cache_contributor(Recorder())
"""

#: Entry attrs that legitimately differ between runs (time, location, ordering).
_VOLATILE_ATTRS = {
    "computed_at",
    "config_identity",
    "order",
    # Compared on their own below.
    "fingerprint",
    "source_sha256",
}

PATHS = ("headless", "gui_run", "gui_sweep", "cli_sweep")


def _snapshot(cfg: Path, record: Path) -> Dict[str, Dict[str, Any]]:
    """Everything one path stored, per entry id."""
    store_dir = resolve_store_dir(BoulderRunner.load(str(cfg)), str(cfg))
    assert store_dir is not None
    identity = scenario_store.config_identity(cfg)
    calls: List[Dict[str, Any]] = []
    if record.exists():
        calls = [json.loads(line) for line in record.read_text("utf-8").splitlines()]
    out: Dict[str, Dict[str, Any]] = {}
    for attrs in scenario_store.list_entries(store_dir, identity):
        sid = attrs["id"]
        payload = scenario_store.read_entry(store_dir, sid, identity)
        assert payload is not None
        times = [float(t) for t in payload["times"]]
        out[sid] = {
            "fingerprint": attrs["fingerprint"],
            "attrs": {k: v for k, v in attrs.items() if k not in _VOLATILE_ATTRS},
            "source": attrs["source_sha256"],
            "code": payload["code_str"],
            # Contributor calls for this entry (by its fingerprint), then the
            # sweep hooks fired for it (by scenario id).
            "contributors": sum(
                c["kind"] == "contributor" and c["fingerprint"] == attrs["fingerprint"]
                for c in calls
            ),
            "hooks": sorted(
                c["kind"]
                for c in calls
                if c["kind"] != "contributor" and c["sid"] == sid
            ),
            "grid": (
                len(times),
                round(times[-1], 9) if times else None,
                round(times[1] - times[0], 9) if len(times) > 1 else None,
            ),
        }
    return out


def _wait(poll, done, what: str) -> Any:
    deadline = time.time() + 120
    while time.time() < deadline:
        state = poll()
        if done(state):
            return state
        time.sleep(0.2)
    raise TimeoutError(what)


def _run_gui(cfg: Path, which: str) -> None:
    """Drive the API as ``boulder.cli`` configures it (class attrs set pre-lifespan)."""
    api_main._converter_class = getattr(BoulderRunner, "converter_class", None)
    api_main._runner_class = BoulderRunner  # type: ignore[assignment]
    app = api_main.create_app()
    with TestClient(app) as client:
        overlays = app.state.preloaded_raw.get("scenarios") or {}
        if which == "gui_sweep":
            resp = client.post("/api/sweep/run", json={"scenarios": overlays})
            assert resp.status_code == 200, resp.text
            job = _wait(
                lambda: client.get("/api/sweep/status").json(),
                lambda j: j["status"] not in ("running", "stopping"),
                "sweep",
            )
            assert job["status"] == "done", job
            return
        for scenario_id in (None, "hot"):
            body: Dict[str, Any] = {"scenarios": overlays}
            if scenario_id:
                body["scenario_id"] = scenario_id
            resp = client.post("/api/simulations", json=body)
            assert resp.status_code == 200, resp.text
            sim_id = resp.json()["simulation_id"]
            result = _wait(
                lambda: client.get(f"/api/simulations/{sim_id}/results").json(),
                lambda r: r["status"] != "running",
                "run",
            )
            assert result["status"] == "complete", result.get("error_message")


def _run_path(which: str, cfg: Path) -> None:
    if which == "headless":
        cli.main([str(cfg), "--headless", "--run"])
    elif which == "cli_sweep":
        with pytest.raises(SystemExit) as exit_info:
            cli.main([str(cfg), "--sweep", "--headless"])
        assert exit_info.value.code == 0
    else:
        _run_gui(cfg, which)


def _split_config() -> Tuple[str, str]:
    """Return ``(base, leaf)``: the network in a parent file, the run-set in a ``from:`` leaf."""
    network, _, scenarios = _CONFIG.partition("scenarios:\n")
    return network, "from: base.yaml\nscenarios:\n" + scenarios


def _definition_of(cfg: Path) -> str:
    """Return the stored run definition of the base entry, as text."""
    store_dir = resolve_store_dir(BoulderRunner.load(str(cfg)), str(cfg))
    assert store_dir is not None
    source = scenario_store.read_source(store_dir, "BASELINE")
    assert source is not None
    return source.definition


@pytest.fixture(scope="module", params=("flat", "from"))
def snapshots(request, tmp_path_factory) -> Dict[str, Dict[str, Any]]:
    """Solve the config through each path once; return what each stored.

    The config is one file (``flat``) or a ``from:`` leaf over a parent file
    (``from``). ``snaps["_rerun"]`` holds, per path, the fingerprint of the base
    entry when the stored definition is run alone, as its own file;
    ``snaps["_files"]`` the user's files, before and after, per path.
    """
    root = tmp_path_factory.mktemp("epm")
    mech_dir = root / "mech"
    mech_dir.mkdir()
    shutil.copy(
        Path(ct.__file__).parent / "data" / "gri30.yaml", mech_dir / "gri30.yaml"
    )
    (root / "epm_host_plugin.py").write_text(_PLUGIN, encoding="utf-8")

    patch = pytest.MonkeyPatch()
    patch.syspath_prepend(str(root))
    patch.setenv("BOULDER_PLUGINS", "epm_host_plugin")
    patch.setenv("EPM_MECH_DIR", str(mech_dir))
    patch.setenv(
        "PYTHONPATH", os.pathsep.join([str(root), os.environ.get("PYTHONPATH", "")])
    )
    patch.setattr(api_main, "_converter_class", None)
    patch.setattr(api_main, "_runner_class", None)
    patch.delenv("BOULDER_NO_CACHE", raising=False)
    snaps: Dict[str, Any] = {"_rerun": {}, "_files": {}}
    try:
        for which in PATHS:
            folder = root / which
            folder.mkdir()
            cfg = folder / "config.yaml"
            files = {cfg: _CONFIG}
            if request.param == "from":
                base, leaf = _split_config()
                files = {cfg: leaf, folder / "base.yaml": base}
            for path, text in files.items():
                path.write_bytes(text.encode("utf-8"))  # no newline translation
            record = folder / "calls.jsonl"
            patch.setenv("EPM_RECORD", str(record))
            patch.setenv("BOULDER_CONFIG_PATH", str(cfg))
            # Fresh plugin discovery per path, with an empty contributor registry.
            patch.setattr(cantera_converter, "_PLUGIN_CACHE", None)
            patch.setattr(
                result_cache.get_cache_contributor_registry(), "contributors", []
            )
            sys.modules.pop("epm_host_plugin", None)
            _run_path(which, cfg)
            snaps[which] = _snapshot(cfg, record)
            snaps["_files"][which] = {
                path: (text.encode("utf-8"), path.read_bytes())
                for path, text in files.items()
            }

            # The stored definition, run alone as its own file.
            alone = folder / "alone"
            alone.mkdir()
            alone_cfg = alone / "config.yaml"
            alone_cfg.write_text(_definition_of(cfg), encoding="utf-8")
            patch.setenv("EPM_RECORD", str(alone / "calls.jsonl"))
            patch.setenv("BOULDER_CONFIG_PATH", str(alone_cfg))
            cli.main([str(alone_cfg), "--headless", "--run"])
            snaps["_rerun"][which] = _snapshot(alone_cfg, alone / "calls.jsonl")[
                "BASELINE"
            ]["fingerprint"]
    finally:
        patch.undo()
    return snaps


#: What is compared for each pair of paths.
PROPERTIES = ("fingerprint", "attrs", "source", "contributors", "hooks", "grid")


def _cases():
    for prop in PROPERTIES:
        for first, second in itertools.combinations(PATHS, 2):
            yield pytest.param(prop, first, second, id=f"{prop}-{first}-{second}")


@pytest.mark.parametrize(("prop", "first", "second"), list(_cases()))
def test_entry_points_agree(snapshots, prop: str, first: str, second: str) -> None:
    """Two entry points store the same *prop* for every entry both can solve.

    ``fingerprint``: the entry's cache key; ``attrs``: its other stored
    attributes (label, node inputs, host KPIs, mechanism through the host
    converter's ``resolve_mechanism``); ``source``: the stored run definition;
    ``contributors`` / ``hooks``: the recording cache contributor and the
    sweep hooks (``scenario_attrs``, ``on_scenario_solved``) calls per entry;
    ``grid``: the stored trajectory's point count, end time and step. Holds for
    a single file and for a ``from:`` leaf.
    """
    common = sorted(set(snapshots[first]) & set(snapshots[second]))
    assert common, "the two paths share no entry"
    for sid in common:
        a, b = snapshots[first][sid], snapshots[second][sid]
        assert a[prop] == b[prop], f"{sid}: {first}={a[prop]!r} {second}={b[prop]!r}"


@pytest.mark.parametrize("which", PATHS)
def test_stored_definition_run_alone_has_the_same_fingerprint(snapshots, which) -> None:
    """The stored (resolved) definition, run alone as a file, hashes to the same entry.

    The definition keeps no ``from:``: it is the whole config, so anyone holding
    only the stored or downloaded YAML reproduces the cache key.
    """
    assert snapshots["_rerun"][which] == snapshots[which]["BASELINE"]["fingerprint"]


@pytest.mark.parametrize("which", PATHS)
def test_a_run_never_writes_the_users_files(snapshots, which) -> None:
    """The user's YAML files are byte-identical after a run, whichever path ran it."""
    for path, (before, after) in snapshots["_files"][which].items():
        assert before == after, f"{path.name} was modified"


# ---------------------------------------------------------------------------
# Fifth path: the downloaded script, and run_continuation
# ---------------------------------------------------------------------------

#: Two mechanisms, a by-name switch (the plugin above) between them.
_SWITCH_CONFIG = """\
phases:
  gas:
    mechanism: gri30.yaml
stages:
  stage_a:
    mechanism: gri30.yaml
    solve: advance_to_steady_state
  stage_b:
    mechanism: h2o2.yaml
    solve: advance_to_steady_state
stage_a:
- id: r_a
  ExampleReactor:
    volume: 1.0e-5
    initial: {temperature: 1100, pressure: 101325, composition: "H2:2, O2:1, N2:4, CO2:1"}
stage_b:
- id: r_b
  IdealGasConstPressureMoleReactor:
    volume: 5.0e-6
    initial: {temperature: 600, pressure: 101325, composition: "N2:1"}
- id: a_to_b
  source: r_a
  target: r_b
  MassFlowController: {mass_flow_rate: 1.0e-4}
  mechanism_switch: {htol: 1.0e-2, Xtol: 1.0e-2}
"""

#: Dumps what a solve left: every reactor (stream points included) and the
#: trajectory.  Pasted at the end of the downloaded script and called in-process.
_DUMP = textwrap.dedent(
    """
    def boulder_dump(converter, trajectory):
        import os

        reactors = {}
        for rid, r in sorted(converter.reactors.items()):
            ph = r.phase
            reactors[rid] = {
                "T": float(ph.T),
                "P": float(ph.P),
                "X": {
                    s: float(x) for s, x in zip(ph.species_names, ph.X) if x > 1e-12
                },
            }
        segments = [
            {
                "stage": seg.stage_id,
                "mechanism": os.path.basename(seg.mechanism),
                "T": [float(x) for x in seg.states.T],
                "P": [float(x) for x in seg.states.P],
            }
            for seg in trajectory.segments
        ]
        streams = {
            nid: {
                "mdot": float(meta.get("mdot") or 0.0),
                "top_Y": {k: round(float(v), 9) for k, v in (meta.get("top_Y") or {}).items()},
            }
            for nid, meta in sorted(converter.reactor_meta.items())
            if meta.get("stream_point")
        }
        return {
            "reactors": reactors,
            "trajectory": segments,
            "streams": streams,
            "connections": sorted(converter.connections),
        }
    """
)


def _assert_same_states(a: Dict[str, Any], b: Dict[str, Any]) -> None:
    assert a["reactors"].keys() == b["reactors"].keys()
    for rid, ra in a["reactors"].items():
        rb = b["reactors"][rid]
        assert ra["T"] == pytest.approx(rb["T"], rel=1e-9), rid
        assert ra["P"] == pytest.approx(rb["P"], rel=1e-9), rid
        assert ra["X"].keys() == rb["X"].keys(), rid
        for sp, x in ra["X"].items():
            assert x == pytest.approx(rb["X"][sp], rel=1e-7, abs=1e-12), (rid, sp)
    assert a["connections"] == b["connections"]
    assert a["streams"].keys() == b["streams"].keys()
    for nid, sa in a["streams"].items():
        assert sa["mdot"] == pytest.approx(b["streams"][nid]["mdot"], rel=1e-9), nid
        assert sa["top_Y"] == pytest.approx(b["streams"][nid]["top_Y"], abs=1e-8), nid
    assert len(a["trajectory"]) == len(b["trajectory"])
    for sa, sb in zip(a["trajectory"], b["trajectory"]):
        assert sa["stage"] == sb["stage"]
        assert sa["mechanism"] == sb["mechanism"]
        assert sa["T"] == pytest.approx(sb["T"], rel=1e-9)
        assert sa["P"] == pytest.approx(sb["P"], rel=1e-9)


def _host_env(patch: pytest.MonkeyPatch, root: Path) -> None:
    """Put the host plugin and its mechanism directory in force for *root*."""
    mech_dir = root / "mech"
    mech_dir.mkdir()
    data = Path(ct.__file__).parent / "data"
    for name in ("gri30.yaml", "h2o2.yaml"):
        shutil.copy(data / name, mech_dir / name)
    (root / "epm_host_plugin.py").write_text(_PLUGIN, encoding="utf-8")
    patch.syspath_prepend(str(root))
    patch.setenv("BOULDER_PLUGINS", "epm_host_plugin")
    patch.setenv("EPM_MECH_DIR", str(mech_dir))
    patch.setenv("EPM_RECORD", str(root / "calls.jsonl"))
    # The script's subprocess must import this checkout's Boulder, not another
    # editable install.
    boulder_root = str(Path(cantera_converter.__file__).parent.parent)
    patch.setenv(
        "PYTHONPATH",
        os.pathsep.join([str(root), boulder_root, os.environ.get("PYTHONPATH", "")]),
    )
    patch.setattr(cantera_converter, "_PLUGIN_CACHE", None)
    patch.delitem(sys.modules, "epm_host_plugin", raising=False)


@pytest.fixture(scope="module", params=("flat", "from", "switch"))
def script_and_pipeline(request, tmp_path_factory) -> Dict[str, Any]:
    """Solve one config by the pipeline and by its downloaded script; return both dumps."""
    root = tmp_path_factory.mktemp("epm_script")
    cfg = root / "config.yaml"
    if request.param == "switch":
        cfg.write_text(_SWITCH_CONFIG, encoding="utf-8")
    elif request.param == "from":
        base, leaf = _split_config()
        (root / "base.yaml").write_text(base, encoding="utf-8")
        cfg.write_text(leaf, encoding="utf-8")
    else:
        cfg.write_text(_CONFIG, encoding="utf-8")

    patch = pytest.MonkeyPatch()
    _host_env(patch, root)
    try:
        script = root / "downloaded.py"
        scope: Dict[str, Any] = {}
        exec(_DUMP, scope)  # noqa: S102 - our own helper text

        # The script users receive: the real download entry, ``--headless --download``.
        from epm_host_plugin import HostRunner  # written by _host_env

        cli.main(
            [str(cfg), "--headless", "--download", str(script)],
            runner_class=HostRunner,
        )
        text = script.read_text("utf-8")
        runner = BoulderRunner.from_yaml(str(cfg))
        runner.build()
        converter = runner.converter
        assert converter is not None and converter._staged_trajectory is not None
        pipeline = scope["boulder_dump"](converter, converter._staged_trajectory)

        out = root / "script_dump.json"
        script.write_text(
            script.read_text("utf-8")
            + _DUMP
            + "\nimport json\n"
            + f"json.dump(boulder_dump(converter, trajectory), open({str(out)!r}, 'w'))\n",
            encoding="utf-8",
        )
        run = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(root),
        )
        assert run.returncode == 0, run.stderr[-3000:]
        return {
            "case": request.param,
            "text": text,
            "pipeline": pipeline,
            "script": json.loads(out.read_text("utf-8")),
        }
    finally:
        patch.undo()


def test_downloaded_script_agrees_with_the_pipeline(script_and_pipeline) -> None:
    """The downloaded script, run in a subprocess, leaves the pipeline's states.

    Asserts the reactor states (stream-point reservoirs included: T, P, X) and
    the trajectory segments (stage, mechanism, T, P) of the script equal those
    of the pipeline's one solve, for a single file, a ``from:`` leaf and a
    gri30 -> h2o2 case switched by name.
    """
    _assert_same_states(script_and_pipeline["script"], script_and_pipeline["pipeline"])


#: The class table each case's script must carry: node -> fully qualified class.
_LISTED = {
    "flat": {"reactor": "cantera.reactor.IdealGasReactor"},
    "from": {"reactor": "cantera.reactor.IdealGasReactor"},
    "switch": {
        "r_a": "epm_host_plugin.ExampleReactor",
        "r_b": "cantera.reactor.IdealGasConstPressureMoleReactor",
    },
}


def test_downloaded_script_lists_the_classes_that_run(script_and_pipeline) -> None:
    """The downloaded script names, stage by stage, the class each node runs.

    Asserts the script written by ``--headless --download`` has one
    ``runner.solve_stage`` call per stage, lists every node with its fully
    qualified class (the host's own subclass included) and checks the built
    objects against it (``EXPECTED_CLASSES``); the script itself ran in the
    fixture, so a wrong class would have raised.
    """
    case, text = script_and_pipeline["case"], script_and_pipeline["text"]
    assert text.count("runner.solve_stage(") == (2 if case == "switch" else 1)
    for node, name in _LISTED[case].items():
        assert f"#     {node}: {name}\n" in text
        assert f"{node!r}: {name!r}" in text
    assert "check_classes(stages[" in text


def test_downloaded_script_uses_the_host_runner_class(script_and_pipeline) -> None:
    """The downloaded script imports and uses the runner class that wrote it.

    Asserts the script written by ``--headless --download`` with a host runner
    subclass imports it from the host plugin and builds ``HostRunner(config)``,
    never the base ``BoulderRunner``; the script ran in the fixture and agrees
    with the pipeline (``test_downloaded_script_agrees_with_the_pipeline``).
    """
    text = script_and_pipeline["text"]
    assert "from epm_host_plugin import HostRunner\n" in text
    assert "runner = HostRunner(config)" in text
    assert "BoulderRunner" not in text


def test_every_path_stores_the_runner_based_script(snapshots) -> None:
    """Every entry point stores the runner-based script as the entry's code.

    Asserts the stored ``code_str`` of each path is the staged script: a
    ``runner.solve_stage`` call and the listed class of the reactor.
    """
    for which in PATHS:
        for sid, entry in snapshots[which].items():
            code = entry["code"]
            assert "runner.solve_stage(" in code, (which, sid)
            assert "#     reactor: cantera.reactor.IdealGasReactor" in code, (
                which,
                sid,
            )


def test_run_continuation_agrees_with_the_pipeline_at_the_updated_value(
    tmp_path, monkeypatch
) -> None:
    """Three ``run_continuation`` steps (x0.5) end where the pipeline does at the last value.

    Asserts the recorded parameter is 1e-4, 5e-5, 2.5e-5 and that the reactor and
    trajectory states after the third step equal a fresh pipeline solve of the
    same config with the mass flow rate set to 2.5e-5, on the gri30 -> h2o2
    by-name switch case (the updated connection crosses the stage boundary).
    """
    _host_env(monkeypatch, tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_SWITCH_CONFIG, encoding="utf-8")
    at_last_value = tmp_path / "last.yaml"
    assert "mass_flow_rate: 1.0e-4" in _SWITCH_CONFIG
    at_last_value.write_text(
        _SWITCH_CONFIG.replace("mass_flow_rate: 1.0e-4", "mass_flow_rate: 2.5e-5"),
        encoding="utf-8",
    )
    scope: Dict[str, Any] = {}
    exec(_DUMP, scope)  # noqa: S102 - our own helper text

    pipeline = BoulderRunner.from_yaml(str(at_last_value))
    pipeline.build()
    assert pipeline.converter is not None
    expected = scope["boulder_dump"](
        pipeline.converter, pipeline.converter._staged_trajectory
    )

    stepped = BoulderRunner.from_yaml(str(cfg))
    stepped.run_continuation(
        {
            "parameter": "connections.a_to_b.mass_flow_rate",
            "update": {"multiply": 0.5},
            "until": {"max_iters": 3},
        }
    )
    assert [r["parameter"] for r in stepped._continuation_rows] == pytest.approx(
        [1.0e-4, 5.0e-5, 2.5e-5]
    )
    assert stepped.converter is not None
    got = scope["boulder_dump"](stepped.converter, stepped.converter._staged_trajectory)
    _assert_same_states(got, expected)
