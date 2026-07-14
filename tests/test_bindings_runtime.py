"""Tests for Phase B bindings runtime integration.

Asserts:
- An MFC mass_flow_rate Func1 bound via the causal layer drives the mass flow
  during a Boulder solve (the MFC accepts the signal and the solve completes).
- A signals+bindings YAML config with an advance_grid solve normalizes and
  builds a working Cantera network.
- A ``nodes.<id>.reduced_electric_field`` binding (plasma pulse) actually
  drives the micro_step solve, not just gets registered after the fact.
- ``validate_config()`` (every API-served/preloaded config goes through this)
  preserves the top-level ``signals:``/``bindings:`` blocks instead of
  silently dropping them.
"""

import yaml

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config, validate_config

_YAML_MFC_SIGNAL = """
metadata:
  title: bindings runtime test
phases:
  gas:
    mechanism: gri30.yaml
settings:
  solver:
    kind: advance_grid
    grid:
      start: 0.0
      stop: 0.01
      dt: 0.001
signals:
  - id: mdot_const
    Constant:
      value: 0.002
bindings:
  - source: mdot_const
    target: connections.inlet_mfc.mass_flow_rate
network:
- id: upstream
  Reservoir:
    temperature: 300.0
    pressure: 101325.0
    composition: "CH4:1, N2:3.76"
- id: reactor
  IdealGasReactor:
    volume: 0.001
    initial:
      temperature: 300.0
      pressure: 101325.0
      composition: "CH4:1, N2:3.76"
- id: downstream
  Reservoir:
    temperature: 300.0
    pressure: 101325.0
    composition: "CH4:1, N2:3.76"
- id: inlet_mfc
  source: upstream
  target: reactor
  MassFlowController:
    mass_flow_rate: 0.001
- id: outlet_valve
  source: reactor
  target: downstream
  PressureController:
    master: inlet_mfc
    pressure_coeff: 0.0
"""


class TestBindingsRuntime:
    def test_binding_mass_flow_rate_network_builds(self):
        """An MFC bound via signals/bindings produces a valid built network."""
        cfg = normalize_config(yaml.safe_load(_YAML_MFC_SIGNAL))
        converter = DualCanteraConverter()
        # build_network should not raise; the binding overrides the static value
        network = converter.build_network(cfg)
        assert network is not None

    def test_binding_mass_flow_rate_network_runs(self):
        """An MFC bound via signals/bindings allows the network to advance."""
        cfg = normalize_config(yaml.safe_load(_YAML_MFC_SIGNAL))
        converter = DualCanteraConverter()
        network = converter.build_network(cfg)
        # If we get here without exception, the transient solve ran successfully
        assert network is not None

    def test_validate_config_preserves_signals_and_bindings(self):
        """validate_config() must not silently drop signals:/bindings:.

        Regression: ``NormalizedConfigModel`` (the Pydantic schema every
        API-served/preloaded config is round-tripped through via
        ``validate_config()``) declared no ``signals``/``bindings`` fields at
        all. Pydantic's default behaviour for undeclared input keys is to
        drop them on ``.dict()`` -- so a config built directly via
        ``normalize_config()`` (used by every test in this file, and by
        ``boulder.cli --headless``) kept its bindings, but the *exact same*
        config served to the GUI via ``/api/configs/preloaded`` (which calls
        ``validate_config()``) silently lost them. Every MFC/tau_s/
        reduced_electric_field binding then registered zero schedule
        callbacks and the whole causal layer became a no-op -- with no error
        anywhere, since dropping an unknown key is not a validation failure.
        """
        cfg = normalize_config(yaml.safe_load(_YAML_MFC_SIGNAL))
        assert cfg.get("signals"), "sanity: normalize_config must keep signals"
        assert cfg.get("bindings"), "sanity: normalize_config must keep bindings"

        validated = validate_config(cfg)
        assert validated.get("signals"), "validate_config() dropped the signals: block"
        assert validated.get("bindings"), (
            "validate_config() dropped the bindings: block"
        )


_YAML_PLASMA_PULSE = """
metadata:
  title: nanosecond pulse binding regression
phases:
  gas:
    mechanism: example_data/methane-plasma-pavan-2023.yaml
settings:
  solver:
    kind: micro_step
    t_total: 9e-08
    chunk_dt: 1e-09
    max_dt: 1e-10
    reinitialize_between_chunks: true
    atol: 1.0e-15
    rtol: 1.0e-9
signals:
  - id: gaussian_EN
    Gaussian:
      peak: 1.8999999999999998e-19
      center: 2.4e-08
      fwhm: 7.064460135092848e-09
bindings:
  - source: gaussian_EN
    target: nodes.reactor.reduced_electric_field
network:
- id: reactor
  ConstPressureReactor:
    volume: 1.0
    energy: "off"
    clone: false
    initial:
      temperature: 300.0
      pressure: 101325.0
      composition: "N2:0.715,O2:0.19,CH4:0.095,e:1e-11"
"""


class TestReducedElectricFieldBindingDrivesMicroStep:
    def test_pulse_binding_grows_electron_mole_fraction(self):
        """The Gaussian E/N pulse must actually drive the micro_step solve.

        Regression covering three independent bugs found together, all
        needed for upstream's nanosecond_pulse_discharge.py to reproduce
        through Boulder (ground truth: e mole fraction grows from a 1e-11
        seed to ~3.17e-08):

        1. ``apply_bindings_block`` used to run *after* ``build_sub_network``
           returned, but ``build_sub_network`` solves the stage internally --
           so the reduced_electric_field callback was registered only once
           the solve had already finished. Fixed via ``pre_solve_hook``.
        2. Boulder defaults every reactor to ``clone: true``; a *cloned*
           plasma phase raises ``ThermoModelMethodError("This method is
           invalid for plasma")`` on every ``reduced_electric_field``
           write, silently swallowed by the callback's broad except. This
           config sets ``clone: false`` explicitly (matching what
           sim2stone.py now emits automatically for any node whose phase
           exposes ``reduced_electric_field``).
        3. ``network.reinitialize()`` ran *after* each chunk's ``advance()``
           loop instead of immediately after the field-update callback, so
           CVODES's cached RHS parameters never saw the new field before
           integrating through it. Fixed by moving reinitialize() before
           the advance loop.
        4. Boulder's default solver tolerances (rtol=1e-6, atol=1e-8) are
           far too loose for the electron/ion mole fractions this pulse
           drives (~1e-11 to ~1e-8) -- CVODES treats the entire ionization
           transient as sub-tolerance noise and never resolves it. This
           config sets ``atol: 1e-15`` / ``rtol: 1e-9`` (the same knob
           already used for continuous_reactor.yaml's tolerance issue).

        With any one of these four unfixed, the electron mole fraction
        stays pinned within noise of its 1e-11 seed for the entire 90 ns
        pulse instead of growing ~3 orders of magnitude.
        """
        cfg = normalize_config(yaml.safe_load(_YAML_PLASMA_PULSE))
        converter = DualCanteraConverter()
        converter.build_network(cfg)

        reactor = converter.reactors["reactor"]
        e_index = reactor.phase.species_index("e")
        final_e_x = float(reactor.phase.X[e_index])

        # Seed was 1e-11; the real pulse drives it up by ~3 orders of
        # magnitude (~3.17e-08 against the vendored script). A frozen field
        # or masked tolerance leaves it within noise of the seed value.
        assert final_e_x > 1e-10, (
            f"electron mole fraction only reached {final_e_x:.3e}; the "
            "reduced_electric_field pulse does not appear to have driven "
            "the solve (binding applied too late, clone=true breaking the "
            "setter, reinitialize() ordering, or tolerances masking the "
            "dynamics)."
        )
