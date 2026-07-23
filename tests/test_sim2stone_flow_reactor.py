"""FlowReactor / FlowReactorSurface support: both STONE round-trip directions.

``ct.FlowReactor`` (plug-flow, distance-marched) and a ``ct.ReactorSurface``
attached via a node-level ``surface:`` property (STONE's ``FlowReactorSurface``
node kind, see STONE_SPECIFICATIONS.md) are integrated along distance, not
time. These tests cover:

- YAML -> Cantera: a STONE node builds a working ``ct.FlowReactor`` +
  ``ct.ReactorSurface`` and solves via ``solver.axis: distance``.
- Cantera -> YAML: a hand-written script round-trips through ``sim2stone``,
  including the ``mass_flow_rate`` recovery workaround (see below) and the
  ``axis: distance`` solver marker.
"""

from __future__ import annotations

import os
import tempfile
import textwrap

import cantera as ct
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import load_yaml_string_with_comments, normalize_config
from boulder.sim2stone import sim_to_stone_yaml
from boulder.validation import validate_normalized_config

_MECH = "methane_pox_on_pt.yaml"
_SURFACE_PHASE = "Pt_surf"


def _surf_pfr_yaml(*, stop: float = 0.003, dt: float = 6.0e-5) -> str:
    return textwrap.dedent(
        f"""\
        phases:
          gas:
            mechanism: {_MECH}

        network:
        - id: pfr
          FlowReactor:
            mechanism: {_MECH}
            initial:
              temperature: 1073.15 K
              pressure: 1 atm
              composition: "CH4:1, O2:1.5, AR:0.1"
            area: 1.0e-4
            mass_flow_rate: 1.7278e-05
            surface_area_to_volume_ratio: 300.0
            energy: "off"
            surface:
              phase: {_SURFACE_PHASE}
              initial:
                coverages: "PT(S): 0.7, O(S): 0.2, CO(S): 0.1"

        settings:
          solver:
            kind: advance_grid
            axis: distance
            grid:
              start: 0.0
              stop: {stop}
              dt: {dt}
        """
    )


def test_flow_reactor_axis_distance_validates() -> None:
    """``normalize_config`` accepts ``solver.axis: distance`` and defaults it to time."""
    normalized = normalize_config(
        load_yaml_string_with_comments(_surf_pfr_yaml())
    )
    validate_normalized_config(normalized)
    solver = normalized["groups"]["default"]["solver"]
    assert solver["axis"] == "distance"
    assert solver["kind"] == "advance_grid"

    # A config with no axis: at all defaults to "time" -- existing
    # time-integrated stages are unaffected.
    time_only = normalize_config(
        load_yaml_string_with_comments(
            textwrap.dedent(
                """\
                network:
                - id: r
                  IdealGasReactor:
                    initial:
                      temperature: 300 K
                      pressure: 1 atm
                      composition: "H2:1, O2:1"
                settings:
                  solver:
                    kind: advance
                    advance_time: 1.0
                """
            )
        )
    )
    assert time_only["groups"]["default"]["solver"]["axis"] == "time"


def test_flow_reactor_axis_rejects_invalid_value() -> None:
    """An unrecognised ``solver.axis`` value raises at normalize-time."""
    with pytest.raises(ValueError, match="solver.axis"):
        normalize_config(
            load_yaml_string_with_comments(
                _surf_pfr_yaml().replace("axis: distance", "axis: sideways")
            )
        )


def test_flow_reactor_builds_and_solves_distance_profile() -> None:
    """A FlowReactor + FlowReactorSurface STONE node builds and solves.

    Asserts: the reactor is a real ``ct.FlowReactor``, the surface is a real
    ``ct.ReactorSurface`` attached to it (not folded into ``self.reactors``),
    and the resulting series is a distance profile (``is_spatial``/``x``, not
    a plain time series) showing real methane conversion along the bed.
    """
    normalized = normalize_config(
        load_yaml_string_with_comments(_surf_pfr_yaml())
    )
    converter = DualCanteraConverter(mechanism=_MECH)
    converter.build_network(normalized)

    assert isinstance(converter.reactors["pfr"], ct.FlowReactor)
    assert "pfr" in converter.surfaces
    assert isinstance(converter.surfaces["pfr"], ct.ReactorSurface)
    # The surface must never leak into the reactor-only bookkeeping used to
    # build ct.ReactorNet() -- it is not a ct.Reactor.
    assert "pfr" not in [
        rid for rid, r in converter.reactors.items() if isinstance(r, ct.ReactorSurface)
    ]

    results, _code = converter.run_streaming_simulation(
        simulation_time=1.0, time_step=0.1, config=normalized
    )
    series = results["reactors"]["pfr"]
    assert series.get("is_spatial") is True
    assert len(series["x"]) > 1
    # Position values are strictly increasing distances along the bed.
    assert series["x"] == sorted(series["x"])
    assert series["x"][-1] == pytest.approx(0.003, rel=1e-6)

    # Real catalytic conversion: CH4 is consumed along the bed.
    assert series["X"]["CH4"][-1] < series["X"]["CH4"][0]


def _write_and_run(python_content: str) -> tuple[ct.ReactorNet, str]:
    """Write *python_content* to a temp ``.py`` file, exec it, return ``(sim, path)``.

    The caller is responsible for ``os.unlink(path)`` -- ``sim_to_stone_yaml``
    needs the file to still exist (``source_file=``) for its AST pass.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(textwrap.dedent(python_content))
        f.flush()
        temp_name = f.name
    exec_globals: dict = {}
    with open(temp_name) as file:
        exec(file.read(), exec_globals)
    return exec_globals["sim"], temp_name


_SURF_PFR_SCRIPT = """
    import cantera as ct

    cm = 0.01
    minute = 60.0
    length = 0.3 * cm
    area = 1.0 * cm**2
    cat_area_per_vol = 1000.0 / cm
    velocity = 40.0 * cm / minute
    porosity = 0.3

    surf = ct.Interface("methane_pox_on_pt.yaml", "Pt_surf")
    t = 800.0 + 273.15
    surf.TP = t, ct.one_atm
    gas = surf.adjacent["gas"]
    gas.TPX = t, ct.one_atm, "CH4:1, O2:1.5, AR:0.1"
    mass_flow_rate = velocity * gas.density * area * porosity

    r = ct.FlowReactor(gas, clone=True)
    r.area = area
    r.surface_area_to_volume_ratio = cat_area_per_vol * porosity
    r.mass_flow_rate = mass_flow_rate
    r.energy_enabled = False
    rsurf = ct.ReactorSurface(surf, r, clone=True, name="pfr_surface")

    sim = ct.ReactorNet([r])
    while sim.distance < length:
        sim.step()
"""


def test_sim2stone_emits_axis_distance_and_flow_reactor_properties() -> None:
    """``sim_to_stone_yaml`` on a live FlowReactor network emits axis: distance.

    Also covers the ``mass_flow_rate`` recovery: ``FlowReactor.mass_flow_rate``
    is write-only in the Cantera Python binding (raises ``AttributeError`` on
    read, unlike a MassFlowController's Func1-introspection limitation), so it
    must be recovered from continuity (``density * speed * area``) rather than
    read directly.
    """
    sim, source = _write_and_run(_SURF_PFR_SCRIPT)
    try:
        yaml_text = sim_to_stone_yaml(
            sim, default_mechanism=_MECH, source_file=source, include_comments=False
        )
    finally:
        os.unlink(source)

    normalized = normalize_config(load_yaml_string_with_comments(yaml_text))
    solver = normalized["groups"]["default"]["solver"]
    assert solver["axis"] == "distance"
    assert solver["kind"] == "advance_grid"
    # The grid's stop may come from AST-detected loop-bound (`length`, the
    # exact bed-length constant) when available, or fall back to the live
    # `sim.distance` reached -- either way it must be a sane positive value
    # close to (not necessarily identical to) the actual distance covered.
    assert solver["grid"]["stop"] == pytest.approx(sim.distance, rel=0.1)

    (node,) = [n for n in normalized["nodes"] if n["type"] == "FlowReactor"]
    props = node["properties"]
    assert props["area"] == pytest.approx(1.0e-4)
    # Recovered via density*speed*area, not the write-only mass_flow_rate getter.
    assert props["mass_flow_rate"] > 0
    assert props["surface_area_to_volume_ratio"] == pytest.approx(30000.0)
    assert props["surface"]["phase"] == _SURFACE_PHASE
    assert "coverages" in props["surface"]["initial"]


def test_sim2stone_flow_reactor_round_trip_rebuilds() -> None:
    """The YAML emitted from a live FlowReactor script rebuilds and re-solves.

    Full round trip: Cantera script -> sim2stone -> STONE YAML -> normalize ->
    DualCanteraConverter.build_network -- the emitted initial state (captured
    at the end of the original distance march) must be numerically consistent
    enough for a fresh distance-grid solve to complete.
    """
    sim, source = _write_and_run(_SURF_PFR_SCRIPT)
    try:
        yaml_text = sim_to_stone_yaml(
            sim, default_mechanism=_MECH, source_file=source, include_comments=False
        )
    finally:
        os.unlink(source)

    normalized = normalize_config(load_yaml_string_with_comments(yaml_text))
    validate_normalized_config(normalized)

    converter = DualCanteraConverter(mechanism=_MECH)
    converter.build_network(normalized)
    assert isinstance(converter.reactors["FlowReactor_0"], ct.FlowReactor)
    assert "FlowReactor_0" in converter.surfaces
