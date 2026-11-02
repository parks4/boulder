"""One config through every run path: the four entry points must agree.

The same run is assembled four ways: headless ``--run``, GUI Run
(``POST /api/simulations``), GUI Sweep (``POST /api/sweep/run``) and CLI
``--sweep --headless``.  A neutral gri30 network with one override scenario is
solved through each, with a host converter subclass (its own
``resolve_mechanism``) and recording hooks registered through a plugin.  For
each pair of paths the stored fingerprint, the stored entry attributes, the
hook / contributor calls and the time grid are compared.  Differences that
exist today are ``xfail(strict=True)`` and name the issue they belong to, so
fixing one turns the test red until the marker is removed.

Notes on the paths: the CLI sweep runs in a real subprocess (as
``boulder --sweep --headless`` does); the other three run in-process.  A
headless single run solves the base entry (``BASELINE``) only; the override
scenario (``hot``) is reachable through GUI Run (``scenario_id``) and both
sweeps.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import sys
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

from boulder.cantera_converter import DualCanteraConverter
from boulder.result_cache import CacheContributorPlugin, register_cache_contributor


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


def register_plugins(plugins):
    plugins.converter_class = HostConverter
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
            body: Dict[str, Any] = {
                "config": app.state.preloaded_config,
                "scenarios": overlays,
            }
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


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Solve the config through each path once; return what each stored."""
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
    snaps: Dict[str, Dict[str, Dict[str, Any]]] = {}
    try:
        for which in PATHS:
            folder = root / which
            folder.mkdir()
            cfg = folder / "config.yaml"
            cfg.write_text(_CONFIG, encoding="utf-8")
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
    finally:
        patch.undo()
    return snaps


#: What is compared for each pair of paths.
PROPERTIES = ("fingerprint", "attrs", "source", "contributors", "hooks", "grid")

#: Known differences today: ``(property, pair)`` -> the issue it belongs to.
#: Remove an entry when its issue is fixed (``strict`` makes the test say so).
_SINGLE = ("headless", "gui_run")
_SWEEP = ("gui_sweep", "cli_sweep")
KNOWN_DIFFERENCES: Dict[Tuple[str, frozenset], str] = {}
for _single, _sweep in itertools.product(_SINGLE, _SWEEP):
    _pair = frozenset((_single, _sweep))
    KNOWN_DIFFERENCES["attrs", _pair] = "parks4/boulder#229"
    KNOWN_DIFFERENCES["hooks", _pair] = "parks4/boulder#229"
for _other in ("headless", "gui_run", "gui_sweep"):
    KNOWN_DIFFERENCES["source", frozenset((_other, "cli_sweep"))] = "parks4/boulder#230"
for _other in ("gui_run", "gui_sweep", "cli_sweep"):
    KNOWN_DIFFERENCES["grid", frozenset(("headless", _other))] = "parks4/boulder#231"


def _cases():
    for prop in PROPERTIES:
        for first, second in itertools.combinations(PATHS, 2):
            reason = KNOWN_DIFFERENCES.get((prop, frozenset((first, second))))
            marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
            yield pytest.param(
                prop, first, second, marks=marks, id=f"{prop}-{first}-{second}"
            )


@pytest.mark.parametrize(("prop", "first", "second"), list(_cases()))
def test_entry_points_agree(snapshots, prop: str, first: str, second: str) -> None:
    """Two entry points store the same *prop* for every entry both can solve.

    ``fingerprint``: the entry's cache key; ``attrs``: its other stored
    attributes (label, node inputs, host KPIs, mechanism through the host
    converter's ``resolve_mechanism``); ``source``: the stored run definition;
    ``contributors`` / ``hooks``: the recording cache contributor and the
    sweep hooks (``scenario_attrs``, ``on_scenario_solved``) calls per entry;
    ``grid``: the stored trajectory's point count, end time and step.
    """
    common = sorted(set(snapshots[first]) & set(snapshots[second]))
    assert common, "the two paths share no entry"
    for sid in common:
        a, b = snapshots[first][sid], snapshots[second][sid]
        assert a[prop] == b[prop], f"{sid}: {first}={a[prop]!r} {second}={b[prop]!r}"
