"""Generic ``extra_series`` extension to reactor plot series.

A plugin's ``spatial_series_fn`` (attached to ``reactor_meta[reactor_id]``) may
return a dict that includes an ``extra_series`` list: arbitrary named x/y
series that Boulder itself has no built-in concept of. Since the returned
dict is stored verbatim into ``reactors_series[reactor_id]``, this locks that
generic pass-through end to end, through ``run_streaming_simulation`` /
``finalize_results`` and through the composite HDF5 payload store.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config, validate_config
from boulder.payload_store import read_payload, write_payload

_CONFIG: Dict[str, Any] = {
    "metadata": {"description": "extra_series plugin test"},
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "nodes": [
        {
            "id": "feed",
            "type": "Reservoir",
            "properties": {
                "temperature": 300,
                "pressure": 101325,
                "composition": "N2:1",
            },
        },
        {
            "id": "reactor",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "temperature": 300,
                "pressure": 101325,
                "composition": "N2:1",
                "volume": 1.0e-6,
            },
        },
        {
            "id": "exhaust",
            "type": "Reservoir",
            "properties": {
                "temperature": 300,
                "pressure": 101325,
                "composition": "N2:1",
            },
        },
    ],
    "connections": [
        {
            "id": "feed_to_reactor",
            "type": "MassFlowController",
            "source": "feed",
            "target": "reactor",
            "properties": {"mass_flow_rate": 1.0e-5},
        },
        {
            "id": "reactor_to_exhaust",
            "type": "PressureController",
            "source": "reactor",
            "target": "exhaust",
            "properties": {"master": "feed_to_reactor", "pressure_coeff": 0.0},
        },
    ],
}


def _extra_series() -> list:
    return [
        {
            "name": "custom quantity",
            "x": [0.0, 0.1, 0.2],
            "x_label": "Position (m)",
            "y": [1.0, 2.0, 3.0],
            "y_label": "Custom unit",
        }
    ]


def test_spatial_series_fn_extra_series_flows_through_run_streaming_simulation():
    """A spatial_series_fn's extra_series rides verbatim into reactors_series.

    Asserts:
    - ``results["reactors"]["reactor"]["extra_series"]`` equals exactly what
      the fake plugin's ``spatial_series_fn`` returned -- Boulder neither
      inspects nor reshapes it.
    """
    config = validate_config(normalize_config(_CONFIG))
    conv = DualCanteraConverter()
    conv.build_network(config)

    extra_series = _extra_series()

    def _spatial_series_fn() -> Dict[str, Any]:
        r = conv.reactors["reactor"]
        names = list(r.phase.species_names)
        return {
            "is_spatial": True,
            "x": [0.0, 0.1, 0.2],
            "T": [float(r.phase.T)] * 3,
            "P": [float(r.phase.P)] * 3,
            "X": {s: [float(x)] * 3 for s, x in zip(names, r.phase.X)},
            "Y": {s: [float(y)] * 3 for s, y in zip(names, r.phase.Y)},
            "extra_series": extra_series,
        }

    conv.reactor_meta.setdefault("reactor", {})["spatial_series_fn"] = (
        _spatial_series_fn
    )

    results, _ = conv.run_streaming_simulation(
        simulation_time=1.0, time_step=1.0, config=config
    )

    series = results["reactors"]["reactor"]
    assert series.get("is_spatial") is True
    assert series["extra_series"] == extra_series


def test_extra_series_preserved_via_payload_store_meta(tmp_path: Path):
    """``extra_series`` (a list of dicts, not a per-state column) rides in meta.

    Asserts it survives a full write_payload/read_payload round trip verbatim,
    alongside the other flags (``is_spatial``) that already ride in meta.
    """
    extra_series = _extra_series()
    series = {
        "T": [1200.0, 1300.0],
        "P": [101325.0, 101325.0],
        "X": {"N2": [1.0, 1.0]},
        "x": [0.0, 0.1],
        "is_spatial": True,
        "extra_series": extra_series,
    }
    payload = {
        "status": "complete",
        "is_complete": True,
        "times": [0.0],
        "reactors_series": {"pfr": series},
        "reactor_reports": {},
        "connection_reports": {},
        "summary": [],
        "sankey_links": None,
        "sankey_nodes": None,
    }
    h5_path = tmp_path / "result.h5"
    write_payload(h5_path, payload, "gri30.yaml")

    out = read_payload(h5_path)
    rt = out["reactors_series"]["pfr"]
    assert rt.get("is_spatial") is True
    assert rt["extra_series"] == extra_series
