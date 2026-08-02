"""`app.state.preloaded_raw` must stay the pristine, un-normalized snapshot.

The startup lifespan (`boulder.api.main`) stores the freshly loaded config as
``preloaded_raw`` and then normalizes it to build ``preloaded_config``.
`normalize_config` mutates its argument in place (unit coercion and process-
pressure propagation write straight into the nested property dicts), so
normalizing the *same object* retroactively corrupts the snapshot.

That snapshot is the base every scenario overlay is merged onto -- Run Sweep
(`boulder.api.routes.sweep._merged_raw`) and the scenario preview route both
read it. Corrupting it means overlays merge against a config that no longer
matches the file on disk: sibling nodes carry SI-converted and propagated
values they never declared, which then *conflict* with an overlay that
legitimately overrides one boundary node (a spurious STONE v2
"conflicting process pressures" error).
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from boulder.api.main import create_app  # noqa: E402

# `outlet` declares its pressure as a *unit string* and `feed` declares none at
# all -- normalization coerces the former to Pa and propagates it onto the
# latter, so both are visible tripwires for in-place mutation.
_BASE_YAML = """\
metadata:
  description: "preloaded_raw snapshot test"
phases:
  gas:
    mechanism: gri30.yaml
network:
  - id: feed
    Reservoir:
      temperature: 300.0
      composition: "CH4:1"
  - id: reactor
    IdealGasReactor:
      volume: 1.0
      initial:
        temperature: 300.0
        composition: "CH4:1"
  - id: outlet
    OutletSink:
      pressure: "1.05 bar"
  - id: mfc
    MassFlowController:
      mass_flow_rate: 0.01
    source: feed
    target: reactor
  - id: pc
    PressureController:
      master: mfc
    source: reactor
    target: outlet
"""


def _client_fully_preloaded(cfg_path: Path):
    """Start the app the way the CLI does, so the lifespan populates state."""
    os.environ["BOULDER_CONFIG_PATH"] = str(cfg_path)
    try:
        app = create_app()
        client = TestClient(app)
        client.__enter__()
    finally:
        del os.environ["BOULDER_CONFIG_PATH"]
    return client, app


def _network_entry(cfg: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    return next(item for item in cfg["network"] if item["id"] == node_id)


def test_startup_leaves_preloaded_raw_byte_identical_to_the_file(
    tmp_path: Path,
) -> None:
    """The snapshot must equal the on-disk YAML, key for key."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_BASE_YAML, encoding="utf-8")
    on_disk = yaml.safe_load(cfg.read_text(encoding="utf-8"))

    client, app = _client_fully_preloaded(cfg)
    try:
        assert app.state.preloaded_raw == on_disk
    finally:
        client.__exit__(None, None, None)


def test_startup_normalization_does_not_leak_into_preloaded_raw(
    tmp_path: Path,
) -> None:
    """Spell out the two ways normalization used to leak into the snapshot.

    Also asserts the *normalized* config really did get both transformations --
    otherwise the snapshot could look pristine simply because normalization
    never ran, and this test would pass vacuously.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_BASE_YAML, encoding="utf-8")

    client, app = _client_fully_preloaded(cfg)
    try:
        raw = app.state.preloaded_raw
        # 1. Unit strings stay authored -- not coerced to Pa.
        assert _network_entry(raw, "outlet")["OutletSink"]["pressure"] == "1.05 bar"
        # 2. A node that declares no pressure still declares none -- the
        #    propagation pass must not have defaulted one onto it.
        assert "pressure" not in _network_entry(raw, "feed")["Reservoir"]

        # The normalized config, by contrast, must show both -- proving the
        # assertions above aren't passing just because nothing happened.
        nodes = {
            n["id"]: (n.get("properties") or {})
            for n in app.state.preloaded_config["nodes"]
        }
        assert nodes["outlet"]["pressure"] == pytest.approx(105000.0)
        assert nodes["feed"]["pressure"] == pytest.approx(105000.0)
    finally:
        client.__exit__(None, None, None)


def test_preloaded_raw_survives_a_scenario_preview(tmp_path: Path) -> None:
    """Reading routes must not normalize the shared snapshot either.

    `/preview` deep-merges an overlay onto the base and normalizes the result;
    if it normalized the snapshot itself rather than a copy, the first preview
    would corrupt the base for every later merge.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_BASE_YAML, encoding="utf-8")

    client, app = _client_fully_preloaded(cfg)
    try:
        before = copy.deepcopy(app.state.preloaded_raw)
        resp = client.post("/api/scenarios/probe/preview", json={"overlay": {}})
        assert resp.status_code == 200, resp.text
        assert app.state.preloaded_raw == before
    finally:
        client.__exit__(None, None, None)
